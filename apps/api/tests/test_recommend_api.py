from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.exception_queue import (
    ReviewStore,
    set_store,
)
from app.services.recommender import RecommendationResult
from tests.test_exception_queue import DictReviewStore

client = TestClient(app)

_BODY = {
    "seller_id": "seller-abc",
    "seller_surplus_kwh": 50.0,
    "time_of_day": "14:00:00",
    "pool_current_absorption_kwh": 1000,
    "pool_absorption_limit_kwh": 10000,
    "pool_current_consumption_kwh": 500,
}


@pytest.fixture(autouse=True)
def use_dict_store():
    store = DictReviewStore()
    set_store(store)
    yield
    set_store(None)


@patch("app.routers.recommend")
def test_recommend_within_band_auto_approves(mock_recommend):
    mock_recommend.return_value = RecommendationResult(
        recommended_price=0.102,
        recommended_absorption_kwh=50.0,
        direction="local_pool",
        model_used="rules",
    )
    response = client.post("/api/v1/recommend", json=_BODY)
    assert response.status_code == 200
    data = response.json()
    assert data["policy_decision"] == "auto-approved"
    assert data["deviation_reason"] is None
    assert data["review_id"] is None
    assert data["direction"] == "local_pool"


def test_recommend_outside_band_flags_for_review():
    response = client.post("/api/v1/recommend", json=_BODY)
    assert response.status_code == 200
    data = response.json()
    assert data["policy_decision"] == "needs_review"
    assert data["deviation_reason"] is not None
    assert data["review_id"] is not None
    assert data["direction"] in ("local_pool", "import", "export")


@patch("app.routers.recommend")
def test_recommend_import_scenario(mock_recommend):
    mock_recommend.return_value = RecommendationResult(
        recommended_price=0.115,
        recommended_absorption_kwh=50.0,
        direction="import",
        model_used="rules",
    )
    body = {**_BODY, "pool_current_consumption_kwh": 2000}
    response = client.post("/api/v1/recommend", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "import"


@patch("app.routers.recommend")
def test_recommend_export_scenario(mock_recommend):
    mock_recommend.return_value = RecommendationResult(
        recommended_price=0.10,
        recommended_absorption_kwh=2000.0,
        direction="export",
        model_used="rules",
    )
    body = {**_BODY, "seller_surplus_kwh": 5000, "pool_current_absorption_kwh": 8000}
    response = client.post("/api/v1/recommend", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "export"


@patch("app.routers.recommend")
def test_recommend_export_price_is_feed_in_tariff(mock_recommend):
    mock_recommend.return_value = RecommendationResult(
        recommended_price=0.10,
        recommended_absorption_kwh=2000.0,
        direction="export",
        model_used="rules",
    )
    body = {**_BODY, "seller_surplus_kwh": 5000, "pool_current_absorption_kwh": 8000}
    response = client.post("/api/v1/recommend", json=body)
    assert response.status_code == 200
    assert response.json()["recommended_price"] == 0.10


def test_list_pending_reviews():
    # Operator-only — the conftest fixture installs a permissive operator
    # verifier, so any Bearer token is accepted here.
    response = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_resolve_review_end_to_end():
    post_resp = client.post(
        "/api/v1/recommend",
        json={**_BODY, "seller_id": "seller-123"},
    )
    data = post_resp.json()
    review_id = data.get("review_id")
    assert review_id is not None

    resolve_resp = client.post(
        f"/api/v1/reviews/{review_id}/resolve",
        json={"action": "approve", "reason": "Approved after manual review"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resolve_resp.status_code == 200
    result = resolve_resp.json()
    assert result["operator_action"] == "approve"
    assert result["operator_reason"] == "Approved after manual review"


def test_resolve_nonexistent_review_returns_404():
    response = client.post(
        "/api/v1/reviews/nonexistent-id/resolve",
        json={"action": "reject", "reason": "no-op"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404


def test_review_persists_across_fresh_query():
    post_resp = client.post(
        "/api/v1/recommend",
        json={**_BODY, "seller_id": "seller-persist", "seller_surplus_kwh": 75.0},
    )
    data = post_resp.json()
    assert data["review_id"] is not None

    pending_resp = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": "Bearer test-token"},
    )
    pending = pending_resp.json()
    matching = [r for r in pending if r["id"] == data["review_id"]]
    assert len(matching) == 1
    assert matching[0]["deviation_reason"] is not None
