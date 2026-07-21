import os
import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
MIGRATION_FILE = MIGRATIONS_DIR / "20250719000001_initial_schema.sql"

EXPECTED_TABLES = {"profiles", "community_pool", "contributions", "operator_policy"}
EXPECTED_ENUMS = {"seller", "operator", "auto", "human", "pending", "settled"}

ROLE_CHECK = re.compile(r"check\s*\(\s*role\s+in\s+", re.IGNORECASE)
APPROVAL_CHECK = re.compile(r"check\s*\(\s*approval_type\s+in\s+", re.IGNORECASE)
STATUS_CHECK = re.compile(r"check\s*\(\s*status\s+in\s+", re.IGNORECASE)


def test_migration_file_exists():
    assert MIGRATION_FILE.exists(), (
        f"Migration file not found at {MIGRATION_FILE}"
    )


def test_migration_contains_placeholder_warnings():
    sql = MIGRATION_FILE.read_text()
    assert "PLACEHOLDER" in sql, (
        "Migration must flag placeholder values with PLACEHOLDER"
    )
    placeholder_count = sql.count("PLACEHOLDER")
    assert placeholder_count >= 5, (
        f"Expected at least 5 PLACEHOLDER flags, found {placeholder_count}"
    )


def test_migration_creates_expected_tables():
    sql = MIGRATION_FILE.read_text()
    create_statements = re.findall(
        r"create\s+table\s+(?:if\s+not\s+exists\s+)?public\.(\w+)",
        sql,
        re.IGNORECASE,
    )
    found = set(create_statements)
    missing = EXPECTED_TABLES - found
    assert not missing, f"Missing table(s) in migration: {missing}"


def test_migration_has_rls():
    sql = MIGRATION_FILE.read_text()
    rls_count = len(re.findall(r"enable\s+row\s+level\s+security", sql, re.IGNORECASE))
    assert rls_count >= len(EXPECTED_TABLES), (
        f"Expected at least {len(EXPECTED_TABLES)} RLS policies, "
        f"found {rls_count}"
    )


def test_migration_has_role_constraint():
    sql = MIGRATION_FILE.read_text()
    assert ROLE_CHECK.search(sql), (
        "Missing CHECK constraint on profiles.role"
    )


def test_migration_has_approval_type_constraint():
    sql = MIGRATION_FILE.read_text()
    assert APPROVAL_CHECK.search(sql), (
        "Missing CHECK constraint on contributions.approval_type"
    )


def test_migration_has_status_constraint():
    sql = MIGRATION_FILE.read_text()
    assert STATUS_CHECK.search(sql), (
        "Missing CHECK constraint on contributions.status"
    )


def test_migration_has_approval_reason_constraint():
    sql = MIGRATION_FILE.read_text()
    assert "approval_reason_required_for_human" in sql, (
        "Missing constraint requiring approval_reason when approval_type = 'human'"
    )


def test_migration_seeds_default_policy():
    sql = MIGRATION_FILE.read_text()
    assert "insert into public.operator_policy" in sql.lower(), (
        "Missing seed INSERT for operator_policy"
    )


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping end-to-end migration test",
)
@pytest.mark.asyncio
async def test_migration_end_to_end():
    import asyncpg

    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)

    try:
        sql = MIGRATION_FILE.read_text()

        # Run migration inside a transaction we can roll back
        async with conn.transaction():
            await conn.execute(sql)

            # Insert a profile
            profile_id = await conn.fetchval(
                "INSERT INTO public.profiles (id, role, email) "
                "VALUES (gen_random_uuid(), 'seller', 'test@example.com') "
                "RETURNING id"
            )
            assert profile_id is not None, "Failed to insert profile"

            # Read the seeded policy (PLACEHOLDER values)
            policy = await conn.fetchrow(
                "SELECT * FROM public.operator_policy WHERE is_active = true"
            )
            assert policy is not None, "No active operator_policy row"
            assert policy["band_width_percentage"] == 5
            assert policy["seller_uplift_percentage"] == 15

            # Calculate a price within the band for auto-approval
            feed_in = policy["feed_in_tariff_reference"]
            uplift = policy["seller_uplift_percentage"] / 100
            recommended_price = round(feed_in * (1 + uplift), 6)

            # Insert a contribution
            contribution_id = await conn.fetchval(
                """
                INSERT INTO public.contributions
                  (seller_id, kwh_contributed, period_start, period_end,
                   ai_recommended_price, final_approved_price, approval_type,
                   approval_reason, payout_amount, status)
                VALUES
                  ($1, 50.0, '2026-07-01 00:00:00+00', '2026-07-08 00:00:00+00',
                   $2, $2, 'auto',
                   NULL, $3, 'pending')
                RETURNING id
                """,
                profile_id,
                recommended_price,
                recommended_price * 50,
            )
            assert contribution_id is not None, "Failed to insert contribution"

            # Verify the contribution and profile are linked
            row = await conn.fetchrow(
                """
                SELECT c.*, p.role, p.email
                FROM public.contributions c
                JOIN public.profiles p ON p.id = c.seller_id
                WHERE c.id = $1
                """,
                contribution_id,
            )
            assert row is not None, "Contribution join failed"
            assert row["role"] == "seller"
            assert row["status"] == "pending"
            assert row["approval_type"] == "auto"
            assert row["approval_reason"] is None

            # Verify foreign key constraint: deleting profile should fail
            # (ON DELETE RESTRICT)
            with pytest.raises(Exception):
                await conn.execute(
                    "DELETE FROM public.profiles WHERE id = $1", profile_id
                )

            # Update status to settled
            await conn.execute(
                "UPDATE public.contributions SET status = 'settled' WHERE id = $1",
                contribution_id,
            )
            updated = await conn.fetchval(
                "SELECT status FROM public.contributions WHERE id = $1",
                contribution_id,
            )
            assert updated == "settled"

            # Verify CHECK constraint: negative kWh should fail
            with pytest.raises(Exception):
                await conn.execute(
                    """
                    INSERT INTO public.contributions
                      (seller_id, kwh_contributed, period_start, period_end,
                       ai_recommended_price, final_approved_price, approval_type,
                       payout_amount, status)
                    VALUES
                      ($1, -10, '2026-07-01 00:00:00+00', '2026-07-08 00:00:00+00',
                       0.10, 0.10, 'auto', 5.0, 'pending')
                    """,
                    profile_id,
                )

    finally:
        await conn.close()
