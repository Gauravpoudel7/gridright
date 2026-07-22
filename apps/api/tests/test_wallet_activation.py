"""Wallet activation via signed challenge (spec §3.3, §4, §5).

Covers: signed connect succeeds (real ed25519 keypair via solders), unsigned /
bad-signature attempts rejected, replayed and expired nonces rejected, wallet
change logs history and applies next-cycle-only (a contribution snapshotted
against the old wallet is unaffected), and the bound-meter + password
preconditions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from solders.keypair import Keypair

from app.main import app
from app.auth import set_verifier, TokenVerifier
from app.services import wallet_activation
from app.services.wallet_activation import WalletStore, build_challenge_message

SELLER_ID = "seller-uuid"


class DictWalletStore(WalletStore):
    def __init__(self):
        self.profile = {
            "meter_binding_status": "bound",
            "must_change_password": False,
            "wallet_status": "not_connected",
            "wallet_address": None,
        }
        self.challenges: dict[str, dict] = {}  # nonce -> row
        self.history: list[dict] = []

    async def get_profile(self, profile_id):
        return dict(self.profile)

    async def create_challenge(self, profile_id, nonce, expires_at):
        self.challenges[nonce] = {
            "profile_id": profile_id,
            "nonce": nonce,
            "expires_at": expires_at,
            "consumed_at": None,
        }

    async def consume_challenge(self, profile_id, nonce, now_iso):
        row = self.challenges.get(nonce)
        if row is None or row["profile_id"] != profile_id:
            return False
        if row["consumed_at"] is not None:
            return False
        if row["expires_at"] <= now_iso:
            return False
        row["consumed_at"] = now_iso
        return True

    async def set_wallet(self, profile_id, new_wallet):
        self.profile["wallet_address"] = new_wallet
        self.profile["wallet_status"] = "active"

    async def add_history(self, profile_id, old_wallet, new_wallet, signature_verified):
        self.history.append({
            "profile_id": profile_id,
            "old_wallet": old_wallet,
            "new_wallet": new_wallet,
            "signature_verified": signature_verified,
        })


class _SellerVerifier(TokenVerifier):
    def verify(self, token: str) -> dict:
        return {"sub": SELLER_ID, "role": "seller",
                "app_metadata": {"role": "seller"}}


@pytest.fixture
def store():
    s = DictWalletStore()
    wallet_activation.set_store(s)
    yield s
    wallet_activation.set_store(None)


@pytest.fixture
def client():
    set_verifier(_SellerVerifier())
    with TestClient(app) as c:
        yield c
    set_verifier(None)


AUTH = {"Authorization": "Bearer seller"}


def _sign(keypair: Keypair, message: str) -> str:
    return str(keypair.sign_message(message.encode("utf-8")))


def test_signed_connect_succeeds(client, store):
    kp = Keypair()
    address = str(kp.pubkey())

    ch = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    signature = _sign(kp, ch["message"])

    resp = client.post(
        "/api/v1/sellers/me/wallet/verify",
        json={"address": address, "nonce": ch["nonce"], "signature": signature},
        headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["wallet_status"] == "active"
    assert body["wallet_address"] == address
    assert body["applies"] == "immediately"  # first connect

    # History logged with signature_verified=True, old_wallet null (spec §3.3)
    assert len(store.history) == 1
    assert store.history[0]["old_wallet"] is None
    assert store.history[0]["new_wallet"] == address
    assert store.history[0]["signature_verified"] is True


def test_bad_signature_rejected(client, store):
    kp = Keypair()
    other = Keypair()  # sign with the WRONG key
    ch = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    signature = _sign(other, ch["message"])

    resp = client.post(
        "/api/v1/sellers/me/wallet/verify",
        json={"address": str(kp.pubkey()), "nonce": ch["nonce"],
              "signature": signature},
        headers=AUTH,
    )
    assert resp.status_code == 400
    assert store.profile["wallet_status"] == "not_connected"
    assert store.history == []


def test_unsigned_attempt_rejected(client, store):
    """A pasted address with a garbage signature never activates (spec §3.3)."""
    kp = Keypair()
    ch = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    resp = client.post(
        "/api/v1/sellers/me/wallet/verify",
        json={"address": str(kp.pubkey()), "nonce": ch["nonce"],
              "signature": "not-a-real-signature"},
        headers=AUTH,
    )
    assert resp.status_code == 400
    assert store.profile["wallet_status"] == "not_connected"


def test_replayed_nonce_rejected(client, store):
    kp = Keypair()
    address = str(kp.pubkey())
    ch = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    signature = _sign(kp, ch["message"])
    payload = {"address": address, "nonce": ch["nonce"], "signature": signature}

    first = client.post("/api/v1/sellers/me/wallet/verify", json=payload, headers=AUTH)
    assert first.status_code == 200
    # Reusing the same nonce is rejected (single-use)
    replay = client.post("/api/v1/sellers/me/wallet/verify", json=payload, headers=AUTH)
    assert replay.status_code == 400


def test_expired_nonce_rejected(client, store):
    kp = Keypair()
    address = str(kp.pubkey())
    ch = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    # Force the stored challenge to be already expired
    store.challenges[ch["nonce"]]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    signature = _sign(kp, ch["message"])
    resp = client.post(
        "/api/v1/sellers/me/wallet/verify",
        json={"address": address, "nonce": ch["nonce"], "signature": signature},
        headers=AUTH,
    )
    assert resp.status_code == 400


def test_wallet_change_logs_history_and_stays_active(client, store):
    # First connect
    kp1 = Keypair()
    ch1 = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    client.post(
        "/api/v1/sellers/me/wallet/verify",
        json={"address": str(kp1.pubkey()), "nonce": ch1["nonce"],
              "signature": _sign(kp1, ch1["message"])},
        headers=AUTH,
    )

    # Change to a new wallet
    kp2 = Keypair()
    ch2 = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    resp = client.post(
        "/api/v1/sellers/me/wallet/verify",
        json={"address": str(kp2.pubkey()), "nonce": ch2["nonce"],
              "signature": _sign(kp2, ch2["message"])},
        headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["wallet_status"] == "active"  # never reverts (spec §3.3)
    assert body["changed"] is True
    # New wallet takes effect NEXT cycle only
    assert body["applies"] == "next_settlement_cycle"

    # Two history rows: first connect + the change, second carries old_wallet
    assert len(store.history) == 2
    assert store.history[1]["old_wallet"] == str(kp1.pubkey())
    assert store.history[1]["new_wallet"] == str(kp2.pubkey())


def test_wallet_change_does_not_touch_in_flight_contribution(client, store):
    """A contribution snapshotted against the old wallet is unaffected by a
    later wallet change (spec §3.3, §5) — modeled on the payout_wallet snapshot
    performed by exception_queue at decision time."""
    kp1 = Keypair()
    ch1 = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    client.post(
        "/api/v1/sellers/me/wallet/verify",
        json={"address": str(kp1.pubkey()), "nonce": ch1["nonce"],
              "signature": _sign(kp1, ch1["message"])},
        headers=AUTH,
    )
    # A settlement computed now snapshots the CURRENT (old) wallet.
    in_flight_contribution = {"payout_wallet": store.profile["wallet_address"]}

    kp2 = Keypair()
    ch2 = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH).json()
    client.post(
        "/api/v1/sellers/me/wallet/verify",
        json={"address": str(kp2.pubkey()), "nonce": ch2["nonce"],
              "signature": _sign(kp2, ch2["message"])},
        headers=AUTH,
    )
    # The wallet on the profile changed, but the in-flight snapshot did not.
    assert store.profile["wallet_address"] == str(kp2.pubkey())
    assert in_flight_contribution["payout_wallet"] == str(kp1.pubkey())


def test_challenge_requires_bound_meter(client, store):
    store.profile["meter_binding_status"] = "unbound"
    resp = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH)
    assert resp.status_code == 409


def test_challenge_requires_password_changed(client, store):
    store.profile["must_change_password"] = True
    resp = client.post("/api/v1/sellers/me/wallet/challenge", headers=AUTH)
    assert resp.status_code == 409
