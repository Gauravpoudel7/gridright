"""Meter binding state machine tests (spec §3.2, §5).

Covers: successful bind, expired code, invalid code, already-claimed meter
(API-level and store-level uniqueness), retry after failure, terminal `bound`,
binding gated on identity approval, and the pairing rate limit.

Uses an in-memory BindingStore + the SimulatedPairingClient (outcome encoded
in the code prefix) and a controllable clock for the rate-limit window.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import set_verifier, TokenVerifier
from app.services import meter_binding
from app.services.meter_binding import (
    RATE_LIMIT_MAX_ATTEMPTS,
    BindingStore,
    SimulatedPairingClient,
)

SELLER_ID = "seller-uuid"


class DictBindingStore(BindingStore):
    def __init__(self):
        # profile_id -> profile row
        self.profiles: dict[str, dict] = {}
        self.attempts: list[tuple[str, float]] = []

    def seed(self, profile_id, application_status="identity_approved",
             binding_status="unbound", meter_id=None):
        self.profiles[profile_id] = {
            "id": profile_id,
            "application_status": application_status,
            "meter_binding_status": binding_status,
            "meter_id": meter_id,
        }

    async def get_profile_binding(self, profile_id):
        row = self.profiles.get(profile_id)
        return dict(row) if row else None

    async def set_binding_status(self, profile_id, status, meter_id=None):
        prof = self.profiles[profile_id]
        # Emulate the DB unique constraint on profiles.meter_id
        if meter_id is not None:
            for pid, other in self.profiles.items():
                if pid != profile_id and other.get("meter_id") == meter_id:
                    raise Exception("unique constraint violation: meter_id")
            prof["meter_id"] = meter_id
        prof["meter_binding_status"] = status

    async def meter_id_taken(self, meter_id, exclude_profile_id):
        return any(
            p.get("meter_id") == meter_id
            for pid, p in self.profiles.items()
            if pid != exclude_profile_id
        )

    async def record_attempt(self, profile_id, at_epoch):
        self.attempts.append((profile_id, at_epoch))

    async def count_recent_attempts(self, profile_id, since_epoch):
        return sum(
            1 for pid, t in self.attempts
            if pid == profile_id and t >= since_epoch
        )


class SpyPairingClient(SimulatedPairingClient):
    """SimulatedPairingClient that counts how many times the (expensive) meter
    service exchange is actually invoked, so tests can prove short-circuits."""

    def __init__(self):
        self.calls = 0

    async def exchange(self, pairing_code, profile_id):
        self.calls += 1
        return await super().exchange(pairing_code, profile_id)


class _SellerVerifier(TokenVerifier):
    def verify(self, token: str) -> dict:
        return {"sub": SELLER_ID, "role": "seller",
                "app_metadata": {"role": "seller"}}


@pytest.fixture
def store():
    s = DictBindingStore()
    s.seed(SELLER_ID)
    meter_binding.set_store(s)
    meter_binding.set_client(SimulatedPairingClient())
    yield s
    meter_binding.set_store(None)
    meter_binding.set_client(None)


@pytest.fixture
def client():
    set_verifier(_SellerVerifier())
    with TestClient(app) as c:
        yield c
    set_verifier(None)


AUTH = {"Authorization": "Bearer seller"}


def bind(client, code):
    return client.post(
        "/api/v1/sellers/me/meter-binding",
        json={"pairing_code": code},
        headers=AUTH,
    )


def test_successful_bind(client, store):
    resp = bind(client, "GOODCODE-42")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meter_binding_status"] == "bound"
    assert body["meter_id"] == "METER-GOODCODE-42"
    assert store.profiles[SELLER_ID]["meter_binding_status"] == "bound"


def test_invalid_code_fails_and_can_retry(client, store):
    resp = bind(client, "BADCODE")
    assert resp.status_code == 200
    assert resp.json()["meter_binding_status"] == "binding_failed"
    assert resp.json()["reason_code"] == "invalid"
    # meter_id never set on failure (spec §1)
    assert store.profiles[SELLER_ID]["meter_id"] is None

    # Retry with a good code succeeds (spec §3.2: seller can retry)
    resp = bind(client, "GOODCODE-43")
    assert resp.json()["meter_binding_status"] == "bound"


def test_expired_code_fails_with_reason(client, store):
    resp = bind(client, "EXPIRED-99")
    assert resp.status_code == 200
    assert resp.json()["meter_binding_status"] == "binding_failed"
    assert resp.json()["reason_code"] == "expired"


def test_already_claimed_via_service_reason(client, store):
    resp = bind(client, "CLAIMED-11")
    assert resp.json()["meter_binding_status"] == "binding_failed"
    assert resp.json()["reason_code"] == "already_claimed"


def test_meter_uniqueness_across_profiles(client, store):
    """Two profiles cannot bind the same meter_id (spec §5) — API level."""
    store.seed("other-seller", binding_status="bound",
               meter_id="METER-GOODCODE-42")
    resp = bind(client, "GOODCODE-42")
    assert resp.json()["meter_binding_status"] == "binding_failed"
    assert resp.json()["reason_code"] == "already_claimed"
    assert store.profiles[SELLER_ID]["meter_id"] is None


@pytest.mark.asyncio
async def test_meter_uniqueness_db_level(store):
    """If the API-level check races, the store's unique constraint still wins
    and the service degrades to binding_failed."""
    class RacingStore(DictBindingStore):
        async def meter_id_taken(self, meter_id, exclude_profile_id):
            return False  # simulate the race: check passes...

    racing = RacingStore()
    racing.seed(SELLER_ID)
    racing.seed("other", binding_status="bound", meter_id="METER-GOODCODE-42")
    meter_binding.set_store(racing)
    result = await meter_binding.submit_pairing_code(SELLER_ID, "GOODCODE-42")
    # ...but the constraint (emulated in set_binding_status) rejects the write
    assert result["meter_binding_status"] == "binding_failed"
    assert result["reason_code"] == "already_claimed"


def test_bound_is_terminal(client, store):
    bind(client, "GOODCODE-1")
    resp = bind(client, "GOODCODE-2")
    assert resp.status_code == 409
    # Original binding untouched (spec §3.2: no unbind/transfer)
    assert store.profiles[SELLER_ID]["meter_id"] == "METER-GOODCODE-1"


def test_rebind_after_bound_does_not_reach_pairing_service(client, store):
    """Server-side immutability: a second bind with a DIFFERENT valid code is
    rejected without overwriting meter_id AND without invoking the pairing
    exchange (the bound guard runs before any exchange)."""
    spy = SpyPairingClient()
    meter_binding.set_client(spy)

    first = bind(client, "GOODCODE-1")
    assert first.json()["meter_binding_status"] == "bound"
    assert spy.calls == 1

    second = bind(client, "GOODCODE-2")
    assert second.status_code == 409
    # No exchange for the rejected rebind, and state is unchanged.
    assert spy.calls == 1
    assert store.profiles[SELLER_ID]["meter_id"] == "METER-GOODCODE-1"
    assert store.profiles[SELLER_ID]["meter_binding_status"] == "bound"


def test_binding_requires_identity_approval(client, store):
    store.seed(SELLER_ID, application_status="submitted")
    resp = bind(client, "GOODCODE-1")
    assert resp.status_code == 409


def test_empty_code_rejected(client, store):
    resp = bind(client, "   ")
    assert resp.status_code == 422


def test_rate_limit_blocks_burst(client, store, monkeypatch):
    """Spec §4: pairing-code exchange is rate-limited per profile."""
    now = [1000.0]
    monkeypatch.setattr(meter_binding, "_now", lambda: now[0])

    for _ in range(RATE_LIMIT_MAX_ATTEMPTS):
        assert bind(client, "BADCODE").status_code == 200
    resp = bind(client, "GOODCODE-1")
    assert resp.status_code == 429

    # Window slides: attempts age out and the seller may retry
    now[0] += meter_binding.RATE_LIMIT_WINDOW_SECONDS + 1
    resp = bind(client, "GOODCODE-1")
    assert resp.status_code == 200
    assert resp.json()["meter_binding_status"] == "bound"


def test_rate_limit_short_circuits_before_pairing_service(client, store, monkeypatch):
    """The rate-limit rejection happens BEFORE the pairing service is called —
    a locked-out profile cannot even reach the exchange (spec §4: prevent
    brute-forcing meter codes)."""
    now = [5000.0]
    monkeypatch.setattr(meter_binding, "_now", lambda: now[0])
    spy = SpyPairingClient()
    meter_binding.set_client(spy)

    for _ in range(RATE_LIMIT_MAX_ATTEMPTS):
        bind(client, "BADCODE")
    assert spy.calls == RATE_LIMIT_MAX_ATTEMPTS

    # Next attempt is rate-limited — the exchange must NOT be invoked again.
    resp = bind(client, "GOODCODE-1")
    assert resp.status_code == 429
    assert spy.calls == RATE_LIMIT_MAX_ATTEMPTS  # unchanged


def test_get_binding_status(client, store):
    resp = client.get("/api/v1/sellers/me/meter-binding", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"meter_binding_status": "unbound", "meter_id": None}


def test_successful_bind_auto_registers_ingest_device(client, store):
    """Binding bridges to the readings pipeline: the bound meter is registered
    as the seller's ingestion device and the one-time token is returned."""
    from app.services import meter
    from tests.test_meter import DictMeterStore

    meter_store = DictMeterStore()
    meter.set_store(meter_store)
    try:
        resp = bind(client, "GOODCODE-77")
        body = resp.json()
        assert body["meter_binding_status"] == "bound"
        assert body["device_token"].startswith("gr_meter_")
        device = meter_store.devices.get("METER-GOODCODE-77")
        assert device is not None
        assert device["seller_id"] == SELLER_ID
    finally:
        meter.set_store(None)
