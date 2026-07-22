"""Password-change gate (spec §4, §5).

A seller with must_change_password=true is blocked from every seller route
except the change-password endpoint. Once changed, the gate clears and routes
unblock. The gate is enforced server-side via the get_password_changed_seller
dependency — a direct API call cannot bypass it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import set_verifier, TokenVerifier
from app.services import password_gate, meter_binding
from app.services.password_gate import PasswordGateStore

SELLER_ID = "seller-uuid"


class DictPasswordGateStore(PasswordGateStore):
    def __init__(self, must_change=True):
        self.flags = {SELLER_ID: must_change}
        self.passwords: dict[str, str] = {}

    async def get_must_change_password(self, profile_id):
        return self.flags.get(profile_id, True)

    async def change_password(self, profile_id, new_password):
        self.passwords[profile_id] = new_password
        self.flags[profile_id] = False


class _SellerVerifier(TokenVerifier):
    def verify(self, token: str) -> dict:
        return {"sub": SELLER_ID, "role": "seller",
                "app_metadata": {"role": "seller"}}


@pytest.fixture
def gate_store():
    s = DictPasswordGateStore(must_change=True)
    password_gate.set_store(s)
    yield s
    password_gate.set_store(None)


@pytest.fixture
def client():
    set_verifier(_SellerVerifier())
    with TestClient(app) as c:
        yield c
    set_verifier(None)


AUTH = {"Authorization": "Bearer seller"}


def test_gated_route_blocked_while_flag_set(client, gate_store):
    """A gated seller endpoint (meter-binding) returns 403 while the flag is
    set — even with a valid session."""
    resp = client.get("/api/v1/sellers/me/meter-binding", headers=AUTH)
    assert resp.status_code == 403
    assert "password" in resp.json()["detail"].lower()


def test_change_password_endpoint_is_reachable_while_gated(client, gate_store):
    """The change-password route itself is NOT gated (spec §4)."""
    resp = client.post(
        "/api/v1/sellers/me/change-password",
        json={"new_password": "a-strong-new-password"},
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is False
    assert gate_store.flags[SELLER_ID] is False


def test_gate_clears_after_change(client, gate_store):
    # Blocked before
    assert client.get("/api/v1/sellers/me/meter-binding", headers=AUTH).status_code == 403
    # Change password
    client.post(
        "/api/v1/sellers/me/change-password",
        json={"new_password": "a-strong-new-password"},
        headers=AUTH,
    )
    # Unblocked after — the meter-binding service store isn't injected here, so
    # it will try the real Supabase store; assert only that the GATE passed by
    # checking we no longer get the 403 password error.
    meter_binding.set_store(_AlwaysUnbound())
    resp = client.get("/api/v1/sellers/me/meter-binding", headers=AUTH)
    meter_binding.set_store(None)
    assert resp.status_code == 200


def test_change_password_too_short_rejected(client, gate_store):
    resp = client.post(
        "/api/v1/sellers/me/change-password",
        json={"new_password": "short"},
        headers=AUTH,
    )
    assert resp.status_code == 422
    # Flag remains set — the gate must not clear on a rejected change
    assert gate_store.flags[SELLER_ID] is True


class _AlwaysUnbound(meter_binding.BindingStore):
    async def get_profile_binding(self, profile_id):
        return {"meter_binding_status": "unbound", "meter_id": None,
                "application_status": "identity_approved"}

    async def set_binding_status(self, profile_id, status, meter_id=None):
        ...

    async def meter_id_taken(self, meter_id, exclude_profile_id):
        return False

    async def record_attempt(self, profile_id, at_epoch):
        ...

    async def count_recent_attempts(self, profile_id, since_epoch):
        return 0
