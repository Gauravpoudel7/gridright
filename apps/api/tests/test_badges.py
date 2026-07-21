"""Phase 8 — cNFT contribution badge tests.

Core requirement: a seeded seller crossing a threshold triggers exactly one
mint, and does NOT re-mint on subsequent contributions below the next
threshold.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import badge_service
from app.services.badge_service import check_and_mint, compute_newly_crossed

from tests.conftest import DictBadgeStore, FakeBadgeMinter


@pytest.fixture
def store():
    s = DictBadgeStore()
    badge_service.set_store(s)
    return s


@pytest.fixture
def minter():
    m = FakeBadgeMinter()
    badge_service.set_minter(m)
    return m


class TestComputeNewlyCrossed:
    THRESHOLDS = DictBadgeStore.THRESHOLDS

    def test_below_first_threshold_crosses_nothing(self):
        assert compute_newly_crossed(99.9, self.THRESHOLDS, set()) == []

    def test_crossing_first_threshold(self):
        crossed = compute_newly_crossed(120.0, self.THRESHOLDS, set())
        assert [t["threshold_kwh"] for t in crossed] == [100]

    def test_already_earned_threshold_not_returned(self):
        crossed = compute_newly_crossed(120.0, self.THRESHOLDS, {100.0})
        assert crossed == []

    def test_jumping_past_multiple_thresholds_returns_all_in_order(self):
        crossed = compute_newly_crossed(1200.0, self.THRESHOLDS, set())
        assert [t["threshold_kwh"] for t in crossed] == [100, 500, 1000]

    def test_exact_threshold_counts_as_crossed(self):
        crossed = compute_newly_crossed(100.0, self.THRESHOLDS, set())
        assert [t["threshold_kwh"] for t in crossed] == [100]


class TestCheckAndMint:
    async def test_crossing_threshold_mints_exactly_once(self, store, minter):
        # Seeded seller with 120 settled kWh — past the 100 kWh milestone
        store.contributions = [("seller-1", 120.0, "settled")]

        minted = await check_and_mint("seller-1")

        assert len(minted) == 1
        assert minted[0]["threshold_kwh"] == 100
        assert minted[0]["mint_status"] == "minted"
        assert len(minter.mint_calls) == 1

    async def test_no_remint_on_subsequent_contribution_below_next_threshold(
        self, store, minter
    ):
        store.contributions = [("seller-1", 120.0, "settled")]
        await check_and_mint("seller-1")

        # A later contribution settles, cumulative now 180 — still below 500
        store.contributions.append(("seller-1", 60.0, "settled"))
        minted = await check_and_mint("seller-1")

        assert minted == []
        assert len(minter.mint_calls) == 1  # still exactly one mint total

    async def test_repeated_check_and_mint_is_idempotent(self, store, minter):
        store.contributions = [("seller-1", 120.0, "settled")]
        await check_and_mint("seller-1")
        await check_and_mint("seller-1")
        await check_and_mint("seller-1")
        assert len(minter.mint_calls) == 1
        assert len(store.badges) == 1

    async def test_crossing_next_threshold_mints_next_badge(self, store, minter):
        store.contributions = [("seller-1", 120.0, "settled")]
        await check_and_mint("seller-1")

        store.contributions.append(("seller-1", 400.0, "settled"))  # cumulative 520
        minted = await check_and_mint("seller-1")

        assert [m["threshold_kwh"] for m in minted] == [500]
        assert len(minter.mint_calls) == 2

    async def test_jump_past_multiple_thresholds_mints_each_once(self, store, minter):
        store.contributions = [("seller-1", 1500.0, "settled")]
        minted = await check_and_mint("seller-1")
        assert [m["threshold_kwh"] for m in minted] == [100, 500, 1000]
        assert len(minter.mint_calls) == 3

    async def test_pending_and_rejected_contributions_do_not_count(self, store, minter):
        # Same settled-only scope as the seller dashboard's cumulative metric
        store.contributions = [
            ("seller-1", 90.0, "settled"),
            ("seller-1", 50.0, "pending"),
            ("seller-1", 50.0, "rejected"),
        ]
        minted = await check_and_mint("seller-1")
        assert minted == []
        assert minter.mint_calls == []

    async def test_badges_are_per_seller(self, store, minter):
        store.contributions = [
            ("seller-1", 120.0, "settled"),
            ("seller-2", 30.0, "settled"),
        ]
        minted_1 = await check_and_mint("seller-1")
        minted_2 = await check_and_mint("seller-2")
        assert len(minted_1) == 1
        assert minted_2 == []

    async def test_failed_mint_recorded_as_failed(self, store):
        class FailingMinter(badge_service.BadgeMinter):
            async def mint(self, seller_id, label, threshold_kwh):
                r = badge_service.MintResult()
                r.ok = False
                r.asset_id = None
                r.tx_signature = None
                r.error = "devnet unavailable"
                return r

        badge_service.set_minter(FailingMinter())
        store.contributions = [("seller-1", 120.0, "settled")]
        minted = await check_and_mint("seller-1")
        assert minted[0]["mint_status"] == "failed"
        # The badge row still exists (unique constraint holds) so a re-check
        # doesn't attempt a duplicate mint for the same threshold.
        assert len(store.badges) == 1


class TestSettlementTriggersBadgeCheck:
    """An operator approve that settles a contribution runs the badge check."""

    def _operator_client(self):
        return TestClient(app)

    def test_approve_resolution_triggers_mint(self, store, minter):
        client = self._operator_client()

        # Flag a recommendation into the review queue
        resp = client.post("/api/v1/recommend", json={
            "seller_id": "seller-badge",
            "seller_surplus_kwh": 150.0,
            "time_of_day": "14:00:00",
            "pool_current_absorption_kwh": 1000,
            "pool_absorption_limit_kwh": 10000,
            "pool_current_consumption_kwh": 500,
        })
        review_id = resp.json()["review_id"]
        assert review_id is not None

        # The settled contribution puts the seller past the 100 kWh milestone
        store.contributions = [("seller-badge", 150.0, "settled")]

        resolve = client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "approve", "reason": "ok after review"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resolve.status_code == 200
        assert len(minter.mint_calls) == 1
        assert minter.mint_calls[0][0] == "seller-badge"

    def test_approve_still_succeeds_when_minting_raises(self, store):
        """Badge minting is a best-effort side effect. If the minter blows up
        (e.g. BADGE_TREE_ADDRESS unset in the environment), the operator's
        already-committed resolve must not become a 500."""
        class ExplodingMinter(badge_service.BadgeMinter):
            async def mint(self, seller_id, label, threshold_kwh):
                raise KeyError("BADGE_TREE_ADDRESS")

        badge_service.set_minter(ExplodingMinter())
        client = self._operator_client()

        resp = client.post("/api/v1/recommend", json={
            "seller_id": "seller-badge",
            "seller_surplus_kwh": 150.0,
            "time_of_day": "14:00:00",
            "pool_current_absorption_kwh": 1000,
            "pool_absorption_limit_kwh": 10000,
            "pool_current_consumption_kwh": 500,
        })
        review_id = resp.json()["review_id"]
        store.contributions = [("seller-badge", 150.0, "settled")]

        resolve = client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "approve", "reason": "ok after review"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resolve.status_code == 200

    def test_reject_resolution_does_not_trigger_mint(self, store, minter):
        client = self._operator_client()
        resp = client.post("/api/v1/recommend", json={
            "seller_id": "seller-badge",
            "seller_surplus_kwh": 150.0,
            "time_of_day": "14:00:00",
            "pool_current_absorption_kwh": 1000,
            "pool_absorption_limit_kwh": 10000,
            "pool_current_consumption_kwh": 500,
        })
        review_id = resp.json()["review_id"]

        store.contributions = [("seller-badge", 150.0, "settled")]

        client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "reject", "reason": "price too high"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert minter.mint_calls == []


class TestBadgesEndpoint:
    @pytest.fixture
    def seller_client(self):
        from app.auth import TokenVerifier, set_verifier

        class _SellerVerifier(TokenVerifier):
            def verify(self, token: str) -> dict:
                return {"sub": "seller-1", "role": "seller",
                        "app_metadata": {"role": "seller"}}

        set_verifier(_SellerVerifier())
        with TestClient(app) as c:
            yield c
        set_verifier(None)

    async def test_lists_earned_badges(self, store, minter, seller_client):
        store.contributions = [("seller-1", 600.0, "settled")]
        await check_and_mint("seller-1")

        r = seller_client.get("/api/v1/sellers/me/badges",
                              headers={"Authorization": "Bearer token"})
        assert r.status_code == 200
        body = r.json()
        assert [b["threshold_kwh"] for b in body] == [100, 500]
        assert all(b["mint_status"] == "minted" for b in body)
        assert all(b["asset_id"] for b in body)

    def test_requires_auth(self, store, seller_client):
        r = seller_client.get("/api/v1/sellers/me/badges")
        assert r.status_code == 401
