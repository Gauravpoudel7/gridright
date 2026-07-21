"""Shared pytest fixtures for the GridRight API test suite.

The auth fixture installs a permissive operator verifier by default so the
existing recommend/exception-queue tests run unchanged. Tests that exercise
the auth layer itself (test_auth.py) opt out by replacing the verifier.
"""
import os

# Force the auth module into testing mode so JWT signature verification is
# skipped by default. Individual tests can still mint and verify tokens
# with a real secret.
os.environ.setdefault("SUPABASE_AUTH_TESTING", "1")

import pytest

from app.auth import UserProfile, set_verifier
from app.services.exception_queue import set_store
from app.services import badge_service

from tests.test_exception_queue import DictReviewStore


class _PermissiveOperatorVerifier:
    """Accepts any token and returns a synthetic operator profile.

    Allows the existing recommend/exception-queue tests to keep working
    without an Authorization header while we build out the real verifier.
    """

    def verify(self, token: str) -> dict:
        return {
            "sub": "test-operator",
            "role": "operator",
            "email": "test-operator@gridright.test",
        }


class DictBadgeStore(badge_service.BadgeStore):
    """In-memory badge store used as the test default (and by test_badges.py).

    Contributions are seeded via `contributions` (a list of
    (seller_id, kwh, status) tuples) rather than a real table.
    """

    THRESHOLDS = [  # mirrors the PLACEHOLDER seed in migration 000004
        {"threshold_kwh": 100, "label": "Community Contributor — 100 kWh"},
        {"threshold_kwh": 500, "label": "Community Supporter — 500 kWh"},
        {"threshold_kwh": 1000, "label": "Community Champion — 1000 kWh"},
    ]

    def __init__(self):
        self.contributions: list[tuple[str, float, str]] = []
        self.badges: dict[str, dict] = {}
        self._next_id = 1

    async def get_active_thresholds(self):
        return list(self.THRESHOLDS)

    async def get_cumulative_settled_kwh(self, seller_id: str) -> float:
        return sum(
            kwh for sid, kwh, status in self.contributions
            if sid == seller_id and status == "settled"
        )

    async def get_earned_threshold_kwhs(self, seller_id: str) -> set[float]:
        return {
            float(b["threshold_kwh"]) for b in self.badges.values()
            if b["seller_id"] == seller_id
        }

    async def insert_badge(self, seller_id, threshold_kwh, label, kwh_at_mint):
        # Enforce the unique (seller_id, threshold_kwh) constraint like the DB
        for b in self.badges.values():
            if b["seller_id"] == seller_id and b["threshold_kwh"] == threshold_kwh:
                return None
        badge_id = f"badge-{self._next_id}"
        self._next_id += 1
        self.badges[badge_id] = {
            "id": badge_id,
            "seller_id": seller_id,
            "threshold_kwh": threshold_kwh,
            "label": label,
            "kwh_at_mint": kwh_at_mint,
            "asset_id": None,
            "tx_signature": None,
            "mint_status": "pending",
            "created_at": "2026-07-19T00:00:00+00:00",
        }
        return badge_id

    async def mark_badge_minted(self, badge_id, asset_id, tx_signature, ok):
        b = self.badges[badge_id]
        b["asset_id"] = asset_id
        b["tx_signature"] = tx_signature
        b["mint_status"] = "minted" if ok else "failed"

    async def list_badges(self, seller_id: str):
        return sorted(
            (dict(b) for b in self.badges.values() if b["seller_id"] == seller_id),
            key=lambda b: b["threshold_kwh"],
        )


class FakeBadgeMinter(badge_service.BadgeMinter):
    """Records mint calls instead of touching devnet."""

    def __init__(self):
        self.mint_calls: list[tuple[str, str, float]] = []

    async def mint(self, seller_id, label, threshold_kwh):
        self.mint_calls.append((seller_id, label, threshold_kwh))
        result = badge_service.MintResult()
        result.ok = True
        result.asset_id = f"asset-{len(self.mint_calls)}"
        result.tx_signature = f"sig-{len(self.mint_calls)}"
        result.error = None
        return result


@pytest.fixture(autouse=True)
def _use_test_defaults():
    """Install a permissive operator verifier + in-memory stores."""
    set_verifier(_PermissiveOperatorVerifier())
    set_store(DictReviewStore())
    badge_service.set_store(DictBadgeStore())
    badge_service.set_minter(FakeBadgeMinter())
    yield
    set_verifier(None)
    set_store(None)
    badge_service.set_store(None)
    badge_service.set_minter(None)
