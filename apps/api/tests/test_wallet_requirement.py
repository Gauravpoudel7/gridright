"""Tests for wallet_address requirement on operator resolve endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from app.main import app
from app.auth import mint_test_token, set_verifier, JWTTokenVerifier


@pytest.fixture(autouse=True)
def use_test_verifier():
    set_verifier(JWTTokenVerifier(testing=True))
    yield
    set_verifier(None)


def operator_token():
    return mint_test_token(sub="op-1", role="operator", email="op@grid.com")


@pytest.mark.asyncio
async def test_resolve_blocked_without_wallet():
    """Operator without wallet_address gets 422 on resolve."""
    async def _raise(user):
        raise HTTPException(
            status_code=422,
            detail="A registered wallet_address is required. Connect your Phantom wallet first.",
        )

    with patch("app.routers.require_wallet", new=_raise):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/reviews/some-review-id/resolve",
                json={"action": "approve", "reason": "looks good"},
                headers={"Authorization": f"Bearer {operator_token()}"},
            )
    assert resp.status_code == 422
    assert "wallet_address" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_recommend_blocked_without_seller_wallet():
    """Seller without wallet_address cannot list surplus via /recommend."""
    async def _raise(seller_id):
        raise HTTPException(
            status_code=422,
            detail="Seller has no registered wallet_address. Connect a Phantom wallet before listing surplus.",
        )

    with patch("app.routers.require_wallet_for_seller_id", new=_raise):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/recommend",
                json={
                    "seller_id": "seller-no-wallet",
                    "seller_surplus_kwh": 100,
                    "time_of_day": "12:00",
                    "pool_current_absorption_kwh": 100,
                    "pool_absorption_limit_kwh": 1000,
                    "pool_current_consumption_kwh": 500,
                },
            )
    assert resp.status_code == 422
    assert "wallet_address" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_resolve_allowed_with_wallet():
    """Operator with wallet_address passes the wallet check (queue 404 is fine)."""
    async def _ok(user):
        return "7xKXabc123"

    with patch("app.routers.require_wallet", new=_ok):
        with patch("app.services.exception_queue.resolve", new=AsyncMock(return_value=None)):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/reviews/missing-id/resolve",
                    json={"action": "approve", "reason": "looks good"},
                    headers={"Authorization": f"Bearer {operator_token()}"},
                )
    assert resp.status_code == 404
