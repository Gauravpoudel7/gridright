"""Tests for the operator dashboard API (Phase 7).

Covers:
- Per-route operator gating on every /operator/* endpoint (401/403/200).
- Feed, pool, distribution, and aggregate-stats payloads from a seeded store.
- Operator actions (approve/adjust/reject) via /reviews/{id}/resolve updating
  the underlying contribution record and reason log — asserted against the
  stored record, not just the response body.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import TokenVerifier, set_verifier
from app.main import app
from app.services.exception_queue import (
    OperatorAction,
    ReviewStore,
    set_store as set_queue_store,
)
from app.services.operator_dashboard import (
    AggregateStats,
    DistributionItem,
    FeedItem,
    OperatorDashboardStore,
    PoolStatus,
    compute_stats,
    set_store as set_dashboard_store,
)


# --- In-memory stores -------------------------------------------------------

class RecordingReviewStore(ReviewStore):
    """In-memory store mirroring SupabaseReviewStore's resolve-time updates
    (approval_type/approval_reason/reviewed_at/final price/status) so tests
    can assert on the stored contribution record itself."""

    def __init__(self):
        self.records: dict[str, dict[str, Any]] = {}
        self._next_id = 1

    def seed(self, **overrides) -> str:
        review_id = f"contrib-{self._next_id}"
        self._next_id += 1
        record = {
            "id": review_id,
            "seller_id": "seller-1",
            "kwh_contributed": 50.0,
            "ai_recommended_price": 0.13,
            "final_approved_price": 0.13,
            "approval_type": None,
            "approval_reason": None,
            "status": "needs_review",
            "review_reason": "price 8% above reference tariff, band allows 5%",
            "direction": "local_pool",
            "reviewed_at": None,
            "adjusted_price": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        record.update(overrides)
        # Mirror insert-time behavior: payout seeded from the AI price
        record.setdefault(
            "payout_amount",
            round(record["ai_recommended_price"] * record["kwh_contributed"], 6),
        )
        self.records[review_id] = record
        return review_id

    async def add_pending_review(
        self,
        seller_id: str,
        kwh_contributed: float,
        ai_recommended_price: float,
        recommended_absorption_kwh: float,
        deviation_reason: str,
        direction: str = "local_pool",
        model_version: str = "rules",
    ) -> str:
        return self.seed(
            seller_id=seller_id,
            kwh_contributed=kwh_contributed,
            ai_recommended_price=ai_recommended_price,
            final_approved_price=ai_recommended_price,
            review_reason=deviation_reason,
            direction=direction,
            model_version=model_version,
        )

    async def add_auto_approved(
        self,
        seller_id: str,
        kwh_contributed: float,
        ai_recommended_price: float,
        direction: str = "local_pool",
        model_version: str = "rules",
    ) -> str:
        return self.seed(
            seller_id=seller_id,
            kwh_contributed=kwh_contributed,
            ai_recommended_price=ai_recommended_price,
            final_approved_price=ai_recommended_price,
            status="settled",
            approval_type="auto",
            review_reason=None,
            direction=direction,
            model_version=model_version,
        )

    async def list_pending_reviews(self) -> list[dict[str, Any]]:
        return [
            {
                "id": r["id"],
                "kwh_contributed": r["kwh_contributed"],
                "ai_recommended_price": r["ai_recommended_price"],
                "recommended_absorption_kwh": r["kwh_contributed"],
                "deviation_reason": r["review_reason"],
                "created_at": r["created_at"],
                "direction": r["direction"],
            }
            for r in self.records.values()
            if r["status"] == "needs_review"
        ]

    async def resolve_review(
        self,
        review_id: str,
        action: OperatorAction,
        reason: str,
        adjusted_price: float | None = None,
    ) -> dict[str, Any] | None:
        if not reason.strip():
            raise ValueError("Operator reason is required")

        record = self.records.get(review_id)
        if record is None or record["status"] != "needs_review":
            return None

        now = datetime.now(timezone.utc).isoformat()
        record["approval_type"] = "human"
        record["approval_reason"] = reason
        record["reviewed_at"] = now

        if action == OperatorAction.approve:
            record["status"] = "settled"
        elif action == OperatorAction.adjust:
            record["status"] = "settled"
            if adjusted_price is not None:
                record["adjusted_price"] = adjusted_price
                record["final_approved_price"] = adjusted_price
                record["payout_amount"] = round(
                    adjusted_price * record["kwh_contributed"], 6
                )
        elif action == OperatorAction.reject:
            record["status"] = "rejected"

        return {
            "id": review_id,
            "seller_id": record["seller_id"],
            "operator_action": action,
            "operator_reason": reason,
            "adjusted_price": adjusted_price,
            "resolved_at": now,
        }


class DictOperatorDashboardStore(OperatorDashboardStore):
    def __init__(self):
        self.feed_limit_called_with: int | None = None

    async def get_feed(self, limit: int = 50) -> list[FeedItem]:
        self.feed_limit_called_with = limit
        return [
            FeedItem(
                id="c1", seller_id="seller-1", kwh_contributed=50.0,
                ai_recommended_price=0.115, final_approved_price=0.115,
                approval_type="auto", approval_reason=None, status="settled",
                direction="local_pool", deviation_reason=None,
                created_at="2026-07-18T10:00:00+00:00",
            ),
            FeedItem(
                id="c2", seller_id="seller-2", kwh_contributed=30.0,
                ai_recommended_price=0.14, final_approved_price=0.14,
                approval_type=None, approval_reason=None, status="needs_review",
                direction="local_pool",
                deviation_reason="price 8% above reference tariff, band allows 5%",
                created_at="2026-07-18T11:00:00+00:00",
            ),
        ]

    async def get_pool_status(self) -> PoolStatus:
        return PoolStatus(
            total_kwh_contributed=1200.0,
            current_absorption_kwh=800.0,
            absorption_limit_kwh=10000.0,
            pending_import_export=[
                {
                    "id": "c3", "seller_id": "seller-3", "kwh": 500.0,
                    "ai_recommended_price": 0.12, "direction": "import",
                    "deviation_reason": "import recommended: pool shortfall",
                    "created_at": "2026-07-18T12:00:00+00:00",
                }
            ],
        )

    async def get_distribution(self) -> list[DistributionItem]:
        return [
            DistributionItem(seller_id="seller-1", total_kwh=450.0, contribution_count=5),
            DistributionItem(seller_id="seller-2", total_kwh=120.0, contribution_count=2),
        ]

    async def get_aggregate_stats(self) -> AggregateStats:
        return compute_stats(
            [
                {"kwh_contributed": 100.0, "final_approved_price": 0.115, "payout_amount": 11.5},
                {"kwh_contributed": 50.0, "final_approved_price": 0.105, "payout_amount": 5.25},
            ],
            feed_in_tariff=0.10,
            operator_margin_pct=5.0,
        )


# --- Fixtures ---------------------------------------------------------------

class _OperatorVerifier(TokenVerifier):
    def verify(self, token: str) -> dict:
        return {"sub": "op-uuid", "role": "operator", "app_metadata": {"role": "operator"}}


class _SellerVerifier(TokenVerifier):
    def verify(self, token: str) -> dict:
        return {"sub": "seller-uuid", "role": "seller", "app_metadata": {"role": "seller"}}


AUTH = {"Authorization": "Bearer token"}


@pytest.fixture
def review_store():
    store = RecordingReviewStore()
    set_queue_store(store)
    yield store
    set_queue_store(None)


@pytest.fixture
def dashboard_store():
    store = DictOperatorDashboardStore()
    set_dashboard_store(store)
    yield store
    set_dashboard_store(None)


@pytest.fixture
def operator_client(review_store, dashboard_store):
    set_verifier(_OperatorVerifier())
    with TestClient(app) as c:
        yield c
    set_verifier(None)


@pytest.fixture
def seller_client(review_store, dashboard_store):
    set_verifier(_SellerVerifier())
    with TestClient(app) as c:
        yield c
    set_verifier(None)


# --- Auth gating ------------------------------------------------------------

OPERATOR_ENDPOINTS = [
    "/api/v1/operator/feed",
    "/api/v1/operator/pool",
    "/api/v1/operator/distribution",
    "/api/v1/operator/stats",
]


class TestOperatorGating:
    @pytest.mark.parametrize("path", OPERATOR_ENDPOINTS)
    def test_seller_gets_403(self, seller_client, path):
        assert seller_client.get(path, headers=AUTH).status_code == 403

    @pytest.mark.parametrize("path", OPERATOR_ENDPOINTS)
    def test_unauthenticated_gets_401(self, operator_client, path):
        assert operator_client.get(path).status_code == 401

    @pytest.mark.parametrize("path", OPERATOR_ENDPOINTS)
    def test_operator_gets_200(self, operator_client, path):
        assert operator_client.get(path, headers=AUTH).status_code == 200


# --- Read endpoints ---------------------------------------------------------

class TestOperatorFeed:
    def test_feed_returns_items_with_resolution_state(self, operator_client):
        body = operator_client.get("/api/v1/operator/feed", headers=AUTH).json()
        assert len(body) == 2
        auto = body[0]
        assert auto["approval_type"] == "auto"
        assert auto["status"] == "settled"
        flagged = body[1]
        assert flagged["status"] == "needs_review"
        assert "band allows 5%" in flagged["deviation_reason"]

    def test_feed_passes_limit(self, operator_client, dashboard_store):
        operator_client.get("/api/v1/operator/feed?limit=10", headers=AUTH)
        assert dashboard_store.feed_limit_called_with == 10


class TestOperatorPool:
    def test_pool_status_and_pending_import_export(self, operator_client):
        body = operator_client.get("/api/v1/operator/pool", headers=AUTH).json()
        assert body["total_kwh_contributed"] == 1200.0
        assert body["absorption_limit_kwh"] == 10000.0
        assert len(body["pending_import_export"]) == 1
        assert body["pending_import_export"][0]["direction"] == "import"


class TestOperatorDistribution:
    def test_distribution_aggregates_by_seller(self, operator_client):
        body = operator_client.get("/api/v1/operator/distribution", headers=AUTH).json()
        assert [i["seller_id"] for i in body] == ["seller-1", "seller-2"]
        assert body[0]["total_kwh"] == 450.0
        assert body[0]["contribution_count"] == 5


class TestOperatorStats:
    def test_stats_back_profitability_claim(self, operator_client):
        body = operator_client.get("/api/v1/operator/stats", headers=AUTH).json()
        assert body["total_kwh_settled"] == 150.0
        assert body["total_payouts"] == 16.75
        # margin 5% of community billing (final price x kWh):
        # (0.115*100 + 0.105*50) * 0.05 = 16.75 * 0.05
        assert body["total_spread_captured"] == 0.8375
        # uplifts: 15% and 5% → mean 10%
        assert body["average_uplift_percentage"] == 10.0
        assert body["settled_count"] == 2


class TestComputeStats:
    def test_empty_rows_yield_zeroes(self):
        stats = compute_stats([], feed_in_tariff=0.10, operator_margin_pct=5.0)
        assert stats.total_kwh_settled == 0.0
        assert stats.average_uplift_percentage == 0.0
        assert stats.settled_count == 0

    def test_zero_tariff_does_not_divide_by_zero(self):
        stats = compute_stats(
            [{"kwh_contributed": 10.0, "final_approved_price": 0.12, "payout_amount": 1.2}],
            feed_in_tariff=0.0,
            operator_margin_pct=5.0,
        )
        assert stats.average_uplift_percentage == 0.0

    def test_spread_uses_final_price_not_tariff(self):
        """Regression: spread is margin% of community billing (final price x
        kWh). An operator adjust must move the spread; a tariff basis would
        report the same number for both rows below."""
        row_at_tariff_uplift = [
            {"kwh_contributed": 100.0, "final_approved_price": 0.115, "payout_amount": 11.5}
        ]
        row_adjusted_down = [
            {"kwh_contributed": 100.0, "final_approved_price": 0.105, "payout_amount": 10.5}
        ]
        spread_a = compute_stats(row_at_tariff_uplift, 0.10, 5.0).total_spread_captured
        spread_b = compute_stats(row_adjusted_down, 0.10, 5.0).total_spread_captured
        assert spread_a == 0.575  # 100 * 0.115 * 0.05
        assert spread_b == 0.525  # 100 * 0.105 * 0.05
        assert spread_a != spread_b


# --- Operator actions update the underlying record --------------------------

class TestOperatorActionsUpdateRecord:
    def test_approve_updates_record_and_reason_log(self, operator_client, review_store):
        review_id = review_store.seed()
        r = operator_client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "approve", "reason": "Demand spike justifies price"},
            headers=AUTH,
        )
        assert r.status_code == 200
        record = review_store.records[review_id]
        assert record["status"] == "settled"
        assert record["approval_type"] == "human"
        assert record["approval_reason"] == "Demand spike justifies price"
        assert record["reviewed_at"] is not None
        # Approved as recommended — price unchanged
        assert record["final_approved_price"] == record["ai_recommended_price"]

    def test_adjust_updates_price_and_reason_log(self, operator_client, review_store):
        review_id = review_store.seed(ai_recommended_price=0.14, final_approved_price=0.14)
        r = operator_client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "adjust", "reason": "Capping at band limit", "adjusted_price": 0.105},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["adjusted_price"] == 0.105
        record = review_store.records[review_id]
        assert record["status"] == "settled"
        assert record["approval_type"] == "human"
        assert record["approval_reason"] == "Capping at band limit"
        assert record["adjusted_price"] == 0.105
        assert record["final_approved_price"] == 0.105

    def test_adjust_recalculates_payout_amount(self, operator_client, review_store):
        """Regression: payout_amount is seeded from the AI price at insert
        time and must be re-derived from the adjusted price on settle —
        otherwise the seller is paid at a price the operator rejected."""
        review_id = review_store.seed(
            kwh_contributed=100.0, ai_recommended_price=0.14, final_approved_price=0.14
        )
        assert review_store.records[review_id]["payout_amount"] == 14.0
        operator_client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "adjust", "reason": "Capping at band limit", "adjusted_price": 0.105},
            headers=AUTH,
        )
        record = review_store.records[review_id]
        assert record["payout_amount"] == 10.5
        assert record["payout_amount"] == record["final_approved_price"] * record["kwh_contributed"]

    def test_reject_updates_record_and_reason_log(self, operator_client, review_store):
        review_id = review_store.seed()
        r = operator_client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "reject", "reason": "Below cost floor"},
            headers=AUTH,
        )
        assert r.status_code == 200
        record = review_store.records[review_id]
        assert record["status"] == "rejected"
        assert record["approval_type"] == "human"
        assert record["approval_reason"] == "Below cost floor"

    def test_resolved_review_leaves_pending_queue(self, operator_client, review_store):
        review_id = review_store.seed()
        operator_client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "approve", "reason": "ok"},
            headers=AUTH,
        )
        pending = operator_client.get("/api/v1/reviews/pending", headers=AUTH).json()
        assert all(p["id"] != review_id for p in pending)

    def test_seller_cannot_resolve(self, seller_client, review_store):
        review_id = review_store.seed()
        r = seller_client.post(
            f"/api/v1/reviews/{review_id}/resolve",
            json={"action": "approve", "reason": "nope"},
            headers=AUTH,
        )
        assert r.status_code == 403
        assert review_store.records[review_id]["status"] == "needs_review"
