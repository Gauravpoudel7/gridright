"""Tests for the seller dashboard API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import set_verifier
from app.services.seller_dashboard import (
    SellerDashboardStore,
    aggregate_dashboard,
    set_store,
)


class _DictSellerDashboardStore(SellerDashboardStore):
    def __init__(self):
        self.dashboard_called_with: str | None = None
        self.history_called_with: str | None = None

    async def get_dashboard(self, seller_id: str):
        self.dashboard_called_with = seller_id
        from app.services.seller_dashboard import DashboardData
        data = DashboardData()
        data.surplus_this_period = 120.5
        data.cumulative_kwh = 450.0
        data.total_earned = 42.75
        data.period_start = "2026-07-01T00:00:00+00:00"
        data.period_end = "2026-07-08T00:00:00+00:00"
        return data

    async def get_history(self, seller_id: str):
        self.history_called_with = seller_id
        from app.services.seller_dashboard import PeriodHistoryItem
        i1 = PeriodHistoryItem()
        i1.period_start = "2026-07-01T00:00:00+00:00"
        i1.period_end = "2026-07-08T00:00:00+00:00"
        i1.kwh_contributed = 120.5
        i1.amount_earned = 12.05
        i1.status = "settled"
        i2 = PeriodHistoryItem()
        i2.period_start = "2026-06-24T00:00:00+00:00"
        i2.period_end = "2026-07-01T00:00:00+00:00"
        i2.kwh_contributed = 80.0
        i2.amount_earned = 0.0
        i2.status = "pending"
        return [i1, i2]


_TEST_STORE = _DictSellerDashboardStore()


@pytest.fixture(autouse=True)
def _inject_test_store():
    set_store(_TEST_STORE)
    yield
    set_store(None)


@pytest.fixture
def client():
    from app.auth import TokenVerifier
    class _SellerVerifier(TokenVerifier):
        def verify(self, token: str) -> dict:
            return {"sub": "seller-uuid", "role": "seller", "app_metadata": {"role": "seller"}}
    set_verifier(_SellerVerifier())
    with TestClient(app) as c:
        yield c
    set_verifier(None)


class TestSellerDashboard:
    def test_dashboard_returns_expected_fields(self, client):
        r = client.get("/api/v1/sellers/me/dashboard", headers={"Authorization": "Bearer token"})
        assert r.status_code == 200
        body = r.json()
        assert body["surplus_this_period"] == 120.5
        assert body["cumulative_kwh"] == 450.0
        assert body["total_earned"] == 42.75
        assert "period_start" in body
        assert "period_end" in body

    def test_dashboard_calls_store_with_seller_id(self, client):
        _TEST_STORE.dashboard_called_with = None
        client.get("/api/v1/sellers/me/dashboard", headers={"Authorization": "Bearer token"})
        assert _TEST_STORE.dashboard_called_with == "seller-uuid"

    def test_dashboard_requires_seller_role(self, client):
        from app.auth import TokenVerifier
        class _OperatorVerifier(TokenVerifier):
            def verify(self, token: str) -> dict:
                return {"sub": "op-uuid", "role": "operator", "app_metadata": {"role": "operator"}}
        set_verifier(_OperatorVerifier())
        r = client.get("/api/v1/sellers/me/dashboard", headers={"Authorization": "Bearer token"})
        assert r.status_code == 403
        set_verifier(None)

    def test_dashboard_requires_auth(self, client):
        r = client.get("/api/v1/sellers/me/dashboard")
        assert r.status_code == 401


class TestSellerHistory:
    def test_history_returns_list(self, client):
        r = client.get("/api/v1/sellers/me/history", headers={"Authorization": "Bearer token"})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert len(body) == 2
        assert body[0]["kwh_contributed"] == 120.5
        assert body[1]["status"] == "pending"

    def test_history_calls_store_with_seller_id(self, client):
        _TEST_STORE.history_called_with = None
        client.get("/api/v1/sellers/me/history", headers={"Authorization": "Bearer token"})
        assert _TEST_STORE.history_called_with == "seller-uuid"

    def test_history_requires_seller_role(self, client):
        from app.auth import TokenVerifier
        class _OperatorVerifier(TokenVerifier):
            def verify(self, token: str) -> dict:
                return {"sub": "op-uuid", "role": "operator", "app_metadata": {"role": "operator"}}
        set_verifier(_OperatorVerifier())
        r = client.get("/api/v1/sellers/me/history", headers={"Authorization": "Bearer token"})
        assert r.status_code == 403

    def test_history_requires_auth(self, client):
        r = client.get("/api/v1/sellers/me/history")
        assert r.status_code == 401


class TestSellerHistoryExport:
    def test_export_returns_csv(self, client):
        r = client.get("/api/v1/sellers/me/history/export", headers={"Authorization": "Bearer token"})
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "").lower()
        text = r.text
        assert "period_start" in text
        assert "kwh_contributed" in text
        assert "120.5" in text


class TestAggregateDashboard:
    """Scoping regressions: cumulative_kwh/total_earned are settled-only,
    matching the operator distribution view and cNFT badge thresholds."""

    ROWS = [  # newest first, as the store queries them
        {"kwh_contributed": 50.0, "payout_amount": 5.75, "status": "pending",
         "period_start": "2026-07-15", "period_end": "2026-07-19"},
        {"kwh_contributed": 30.0, "payout_amount": 2.7, "status": "rejected",
         "period_start": "2026-07-15", "period_end": "2026-07-19"},
        {"kwh_contributed": 100.0, "payout_amount": 10.5, "status": "settled",
         "period_start": "2026-07-08", "period_end": "2026-07-15"},
        {"kwh_contributed": 100.0, "payout_amount": 11.5, "status": "settled",
         "period_start": "2026-07-01", "period_end": "2026-07-08"},
    ]

    def test_cumulative_kwh_counts_settled_only(self):
        data = aggregate_dashboard(self.ROWS)
        assert data.cumulative_kwh == 200.0  # not 280 (all) or 250 (non-rejected)

    def test_total_earned_counts_settled_only(self):
        data = aggregate_dashboard(self.ROWS)
        assert data.total_earned == 22.0

    def test_surplus_this_period_skips_rejected(self):
        # Newest non-rejected row is the pending 50 kWh contribution; a
        # rejected newest row must not be reported as contributed surplus.
        rows = [self.ROWS[1], self.ROWS[0], *self.ROWS[2:]]
        data = aggregate_dashboard(rows)
        assert data.surplus_this_period == 50.0
        assert data.period_start == "2026-07-15"

    def test_empty_rows(self):
        data = aggregate_dashboard([])
        assert data.cumulative_kwh == 0.0
        assert data.total_earned == 0.0
        assert data.surplus_this_period == 0.0
        assert data.period_start == ""
