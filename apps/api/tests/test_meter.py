"""Phase 2 (advanced roadmap): smart meter ingestion tests.

Uses an in-memory MeterStore, mirroring the DictReviewStore/DictBadgeStore
pattern. Covers: valid reading accepted, unknown device rejected, mismatched
token rejected, malformed/out-of-bounds payload rejected.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services import meter
from app.services.meter import MeterStore, hash_device_token


class DictMeterStore(MeterStore):
    def __init__(self):
        self.devices: dict[str, dict] = {}  # keyed by meter_device_id
        self.readings: list[dict] = []
        self._next_id = 1

    async def get_device(self, meter_device_id):
        return self.devices.get(meter_device_id)

    async def get_device_for_seller(self, seller_id):
        for d in self.devices.values():
            if d["seller_id"] == seller_id:
                return d
        return None

    async def register_device(self, seller_id, meter_device_id, device_token_hash):
        # replace any existing device for this seller (mirrors prod store)
        self.devices = {
            k: v for k, v in self.devices.items() if v["seller_id"] != seller_id
        }
        row = {
            "seller_id": seller_id,
            "meter_device_id": meter_device_id,
            "device_token_hash": device_token_hash,
        }
        self.devices[meter_device_id] = row
        return dict(row)

    async def insert_reading(self, reading):
        row = {**reading, "id": f"reading-{self._next_id}"}
        self._next_id += 1
        # emulate the DB generated column
        row["surplus_kwh"] = max(reading["generation_kwh"] - reading["consumption_kwh"], 0)
        self.readings.append(row)
        return row

    async def get_recent_readings(self, seller_id, limit):
        rows = [r for r in self.readings if r["seller_id"] == seller_id]
        return sorted(rows, key=lambda r: r["reading_at"], reverse=True)[:limit]


DEVICE_ID = "METER-001"
DEVICE_TOKEN = "gr_meter_test_token_abc"


@pytest.fixture()
def meter_store():
    store = DictMeterStore()
    store.devices[DEVICE_ID] = {
        "seller_id": "seller-1",
        "meter_device_id": DEVICE_ID,
        "device_token_hash": hash_device_token(DEVICE_TOKEN),
    }
    meter.set_store(store)
    yield store
    meter.set_store(None)


def reading_payload(**overrides):
    payload = {
        "meter_device_id": DEVICE_ID,
        "reading_at": "2026-07-20T12:00:00+00:00",
        "generation_kwh": 4.2,
        "consumption_kwh": 1.1,
        "grid_export_kwh": 1.2,
    }
    payload.update(overrides)
    return payload


async def post_reading(payload, token=DEVICE_TOKEN):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/api/v1/meter-readings",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )


@pytest.mark.asyncio
async def test_valid_reading_accepted(meter_store):
    resp = await post_reading(reading_payload())
    assert resp.status_code == 201
    assert resp.json()["seller_id"] == "seller-1"
    assert len(meter_store.readings) == 1
    # surplus is computed, floored at 0, never taken from the wire
    assert meter_store.readings[0]["surplus_kwh"] == pytest.approx(3.1)


@pytest.mark.asyncio
async def test_unknown_device_rejected(meter_store):
    resp = await post_reading(reading_payload(meter_device_id="METER-UNKNOWN"))
    assert resp.status_code == 401
    assert len(meter_store.readings) == 0


@pytest.mark.asyncio
async def test_mismatched_token_rejected(meter_store):
    resp = await post_reading(reading_payload(), token="wrong-token")
    assert resp.status_code == 401
    assert len(meter_store.readings) == 0


@pytest.mark.asyncio
async def test_missing_token_rejected(meter_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/meter-readings", json=reading_payload())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_malformed_payload_rejected(meter_store):
    # negative consumption → 422 from bounds validation
    resp = await post_reading(reading_payload(consumption_kwh=-1))
    assert resp.status_code == 422
    # export exceeding generation → 422
    resp = await post_reading(reading_payload(grid_export_kwh=99))
    assert resp.status_code == 422
    # missing field → 422 from pydantic
    bad = reading_payload()
    del bad["generation_kwh"]
    resp = await post_reading(bad)
    assert resp.status_code == 422
    assert len(meter_store.readings) == 0


@pytest.mark.asyncio
async def test_register_then_ingest_roundtrip(meter_store):
    # Register a device for a fresh seller via the service (endpoint auth is
    # covered by the existing get_seller_user tests; this exercises the flow).
    result = await meter.register_device("seller-2", "METER-002")
    token = result["device_token"]
    assert token.startswith("gr_meter_")

    resp = await post_reading(
        reading_payload(meter_device_id="METER-002"), token=token
    )
    assert resp.status_code == 201
    assert resp.json()["seller_id"] == "seller-2"

    recent = await meter.get_recent_readings("seller-2")
    assert len(recent) == 1
