"""Wallet activation via signed challenge (spec §2, §3.3, §4).

Available once `meter_binding_status = bound` and the password has been changed.
Connecting a wallet requires a signed challenge: the backend issues a nonce, the
wallet signs it, and the backend verifies the ed25519 signature server-side
before accepting the address. A pasted/typed address is NEVER accepted without a
valid signature over a fresh, single-use nonce.

State machine (on profiles.wallet_status):
    not_connected → active     (first successful signed connect)
    active → active            (later wallet changes stay active — never reverts)

Every connect/change is logged to wallet_history. A wallet change takes effect
from the NEXT settlement cycle only: existing contributions keep the
payout_wallet snapshotted on them at decision time (see exception_queue), so a
change never rewrites an in-flight payout (spec §3.3).

Signature verification uses solders (already a dependency) — no new packages.
Solana wallets sign with ed25519 over the raw message bytes; the address is the
base58 of the public key.
"""
from __future__ import annotations

import os
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

NONCE_TTL_SECONDS = 300  # 5 minutes


class WalletActivationError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def build_challenge_message(nonce: str) -> str:
    """The exact string the wallet is asked to sign. Kept stable so the client
    and server agree byte-for-byte."""
    return f"GridRight wallet verification\nNonce: {nonce}"


def verify_signature(address: str, message: str, signature_b58: str) -> bool:
    """Verify an ed25519 signature over `message` by `address` (base58 pubkey).

    Accepts base64 (browser transport) or base58 (Solana convention).
    Returns False on any malformed input rather than raising.
    """
    # Outside the try: a missing crypto dependency must be a loud 500 in the
    # logs, not a silent "Signature verification failed" for every seller.
    import base64 as _b64
    from solders.pubkey import Pubkey
    from solders.signature import Signature

    try:
        pubkey = Pubkey.from_string(address)
        msg_bytes = message.encode("utf-8")

        # Try base64 first (what the browser sends via btoa/Array.from).
        sig = None
        for decode in (
            lambda s: _b64.b64decode(s + "=" * (-len(s) % 4)),  # standard b64
            lambda s: _b64.urlsafe_b64decode(s + "=" * (-len(s) % 4)),  # url-safe b64
        ):
            try:
                raw = decode(signature_b58)
                if len(raw) == 64:
                    sig = Signature.from_bytes(raw)
                    break
            except Exception:
                continue

        # Fall back to base58 (Solana native).
        if sig is None:
            sig = Signature.from_string(signature_b58)

        return sig.verify(pubkey, msg_bytes)
    except Exception:
        return False


# --- Data layer --------------------------------------------------------------

class WalletStore(ABC):
    @abstractmethod
    async def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Return {meter_binding_status, must_change_password, wallet_status,
        wallet_address} or None."""

    @abstractmethod
    async def create_challenge(
        self, profile_id: str, nonce: str, expires_at: str
    ) -> None:
        ...

    @abstractmethod
    async def consume_challenge(
        self, profile_id: str, nonce: str, now_iso: str
    ) -> bool:
        """Atomically mark an unconsumed, unexpired nonce for this profile as
        consumed. Returns True if it was valid (and is now consumed), else
        False (unknown/expired/replayed)."""

    @abstractmethod
    async def set_wallet(
        self, profile_id: str, new_wallet: str
    ) -> None:
        """Set wallet_address + wallet_status='active'."""

    @abstractmethod
    async def add_history(
        self,
        profile_id: str,
        old_wallet: str | None,
        new_wallet: str,
        signature_verified: bool,
    ) -> None:
        ...


class SupabaseWalletStore(WalletStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        res = (
            self._client.table("profiles")
            .select("meter_binding_status, must_change_password, wallet_status, "
                    "wallet_address")
            .eq("id", profile_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    async def create_challenge(
        self, profile_id: str, nonce: str, expires_at: str
    ) -> None:
        self._client.table("wallet_challenges").insert(
            {"profile_id": profile_id, "nonce": nonce, "expires_at": expires_at}
        ).execute()

    async def consume_challenge(
        self, profile_id: str, nonce: str, now_iso: str
    ) -> bool:
        # Fetch an unconsumed nonce for this profile.
        res = (
            self._client.table("wallet_challenges")
            .select("id, expires_at, consumed_at")
            .eq("profile_id", profile_id)
            .eq("nonce", nonce)
            .limit(1)
            .execute()
        )
        if not res.data:
            return False
        row = res.data[0]
        if row.get("consumed_at") is not None:
            return False
        if row["expires_at"] <= now_iso:
            return False
        # Mark consumed. The consumed_at IS NULL predicate makes this the
        # single-use gate even under a race (update affects 0 rows the 2nd time).
        upd = (
            self._client.table("wallet_challenges")
            .update({"consumed_at": now_iso})
            .eq("id", row["id"])
            .is_("consumed_at", "null")
            .execute()
        )
        return bool(upd.data)

    async def set_wallet(self, profile_id: str, new_wallet: str) -> None:
        self._client.table("profiles").update(
            {"wallet_address": new_wallet, "wallet_status": "active"}
        ).eq("id", profile_id).execute()

    async def add_history(
        self,
        profile_id: str,
        old_wallet: str | None,
        new_wallet: str,
        signature_verified: bool,
    ) -> None:
        self._client.table("wallet_history").insert(
            {
                "profile_id": profile_id,
                "old_wallet": old_wallet,
                "new_wallet": new_wallet,
                "signature_verified": signature_verified,
            }
        ).execute()


_store: WalletStore | None = None


def _get_store() -> WalletStore:
    global _store
    if _store is None:
        _store = SupabaseWalletStore()
    return _store


def set_store(store: WalletStore | None) -> None:
    global _store
    _store = store


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Operations --------------------------------------------------------------

async def issue_challenge(profile_id: str) -> dict[str, Any]:
    """Issue a fresh single-use nonce for the profile to sign.

    Preconditions (spec §3.3): meter bound and password changed.
    """
    profile = await _get_store().get_profile(profile_id)
    if profile is None:
        raise WalletActivationError(404, "Profile not found")
    if profile.get("meter_binding_status") != "bound":
        raise WalletActivationError(
            409, "Wallet activation requires a bound meter first"
        )
    if profile.get("must_change_password"):
        raise WalletActivationError(
            409, "Change your temporary password before connecting a wallet"
        )

    nonce = secrets.token_urlsafe(24)
    expires_at = (_now() + timedelta(seconds=NONCE_TTL_SECONDS)).isoformat()
    await _get_store().create_challenge(profile_id, nonce, expires_at)
    return {
        "nonce": nonce,
        "message": build_challenge_message(nonce),
        "expires_at": expires_at,
    }


async def verify_and_connect(
    profile_id: str, address: str, nonce: str, signature: str
) -> dict[str, Any]:
    """Verify the signed challenge and connect/update the wallet.

    - Consumes the nonce (single-use, unexpired).
    - Verifies the ed25519 signature server-side.
    - First connect: wallet_status not_connected → active.
    - Later change: stays active; new wallet applies next cycle only.
    - Logs wallet_history either way.
    """
    store = _get_store()
    profile = await store.get_profile(profile_id)
    if profile is None:
        raise WalletActivationError(404, "Profile not found")
    if profile.get("meter_binding_status") != "bound":
        raise WalletActivationError(
            409, "Wallet activation requires a bound meter first"
        )
    if profile.get("must_change_password"):
        raise WalletActivationError(
            409, "Change your temporary password before connecting a wallet"
        )
    if not address or not nonce or not signature:
        raise WalletActivationError(422, "address, nonce, and signature are required")

    # Single-use nonce check FIRST — a replayed or expired nonce is rejected
    # before we even look at the signature.
    consumed = await store.consume_challenge(
        profile_id, nonce, _now().isoformat()
    )
    if not consumed:
        raise WalletActivationError(400, "Invalid, expired, or already-used challenge")

    message = build_challenge_message(nonce)
    if not verify_signature(address, message, signature):
        # Nonce is already consumed (can't be reused); signature failed.
        raise WalletActivationError(400, "Signature verification failed")

    old_wallet = profile.get("wallet_address")
    await store.set_wallet(profile_id, address)
    await store.add_history(
        profile_id, old_wallet, address, signature_verified=True
    )

    return {
        "wallet_status": "active",
        "wallet_address": address,
        "changed": old_wallet is not None and old_wallet != address,
        "applies": "next_settlement_cycle" if old_wallet else "immediately",
    }
