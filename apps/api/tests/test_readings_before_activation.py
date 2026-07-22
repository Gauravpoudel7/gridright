"""Readings before wallet activation (spec §3.4, §5).

Readings keep being ingested and stored regardless of wallet_status — ingestion
is never paused. But a profile whose wallet_status is not_connected is excluded
from settlement: /recommend (the listing/settlement entry point) rejects it
until the wallet goes active.

Settlement is FORWARD-ONLY (implementer decision per spec §3.4/§6, flagged in
the phase report): backlog readings from binding→activation are stored but
never settled retroactively.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch
from fastapi import HTTPException

from app.main import app
from app.services import meter
from app.services.meter import hash_device_token
from tests.test_meter import DictMeterStore

DEVICE_ID = "METER-XYZ"
DEVICE_TOKEN = "gr_meter_test_token_xyz"
SELLER_ID = "seller-not-connected"


@pytest.fixture()
def meter_store():
    store = DictMeterStore()
    store.devices[DEVICE_ID] = {
        "seller_id": SELLER_ID,
        "meter_device_id": DEVICE_ID,
        "device_token_hash": hash_device_token(DEVICE_TOKEN),
    }
    meter.set_store(store)
    yield store
    meter.set_store(None)


def reading_payload():
    return {
        "meter_device_id": DEVICE_ID,
        "reading_at": "2026-07-22T12:00:00+00:00",
        "generation_kwh": 5.0,
        "consumption_kwh": 1.0,
        "grid_export_kwh": 2.0,
    }


def recommend_payload():
    return {
        "seller_id": SELLER_ID,
        "seller_surplus_kwh": 100,
        "time_of_day": "12:00",
        "pool_current_absorption_kwh": 100,
        "pool_absorption_limit_kwh": 1000,
        "pool_current_consumption_kwh": 500,
    }


@pytest.mark.asyncio
async def test_readings_ingested_while_wallet_not_connected(meter_store):
    """Ingestion never checks wallet_status — readings accumulate (spec §3.4)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/meter-readings",
            json=reading_payload(),
            headers={"Authorization": f"Bearer {DEVICE_TOKEN}"},
        )
    assert resp.status_code == 201
    assert len(meter_store.readings) == 1
    assert meter_store.readings[0]["seller_id"] == SELLER_ID


@pytest.mark.asyncio
async def test_recommend_excluded_until_wallet_active(meter_store):
    """The settlement path rejects a not_connected profile (spec §3.4)."""
    async def _not_active(seller_id):
        raise HTTPException(
            status_code=422,
            detail="Seller wallet is not active. Complete the signed wallet "
                   "connect before listing surplus.",
        )

    with patch("app.routers.require_wallet_for_seller_id", new=_not_active):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/recommend", json=recommend_payload())
    assert resp.status_code == 422
    assert "not active" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_recommend_allowed_once_wallet_active(meter_store):
    """Once wallet_status flips to active the same profile can list surplus."""
    async def _active(seller_id):
        return "ActiveWalletAddr111111111111111111111111111"

    with patch("app.routers.require_wallet_for_seller_id", new=_active):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/recommend", json=recommend_payload())
    assert resp.status_code == 200
    assert "recommended_price" in resp.json()


@pytest.mark.asyncio
async def test_get_active_wallet_requires_active_status():
    """Unit: get_active_wallet returns None unless wallet_status='active',
    even when an address is present (forward-only exclusion gate)."""
    from app.services import wallet as wallet_service

    class _Result:
        def __init__(self, data):
            self.data = data

    class _Query:
        def __init__(self, data):
            self._data = data
        def select(self, *_): return self
        def eq(self, *_): return self
        def single(self): return self
        def execute(self): return _Result(self._data)

    class _Client:
        def __init__(self, data):
            self._data = data
        def table(self, *_): return _Query(self._data)

    # Address present but status not_connected → excluded
    with patch.object(wallet_service, "_supabase",
                      return_value=_Client({"wallet_address": "abc",
                                            "wallet_status": "not_connected"})):
        assert await wallet_service.get_active_wallet("s-1") is None

    # Active → included
    with patch.object(wallet_service, "_supabase",
                      return_value=_Client({"wallet_address": "abc",
                                            "wallet_status": "active"})):
        assert await wallet_service.get_active_wallet("s-1") == "abc"
