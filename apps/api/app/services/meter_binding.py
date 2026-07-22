"""Meter binding state machine (spec §2, §3.2).

Reachable only after an application is `identity_approved`. The seller submits
the meter's **pairing code** (not a free-text meter id); the backend exchanges
it with the virtual-smart-meter service for an owner credential, and on success
records the returned `meter_id` and sets `meter_binding_status = bound`.

State machine (on profiles.meter_binding_status):
    unbound → pairing_pending → bound            (success, meter_id recorded)
                              → binding_failed    (invalid/expired/claimed code)
    binding_failed → pairing_pending → ...        (retry with a new code)
`bound` is TERMINAL and irreversible — no unbind/transfer path (spec §3.2, §6).

Security (spec §4):
  - Pairing-code exchange is rate-limited per profile (sliding window) to
    prevent brute-forcing meter codes.
  - `meter_id` uniqueness is enforced both here (friendly "already claimed"
    error) and by the DB unique constraint on profiles.meter_id.

The virtual-smart-meter service doesn't exist in-repo yet, so the exchange goes
through a swappable `PairingClient` (HTTP impl against METER_SERVICE_URL; a
deterministic simulated impl when unset), mirroring the BadgeMinter pattern.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Rate limit: at most this many exchange attempts per profile per window.
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 600  # 10 minutes


class MeterBindingError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class PairingResult:
    ok: bool
    meter_id: str | None = None
    # reason categories: "invalid", "expired", "already_claimed"
    reason: str | None = None


# --- Virtual-smart-meter service client -------------------------------------

class PairingClient(ABC):
    @abstractmethod
    async def exchange(self, pairing_code: str, profile_id: str) -> PairingResult:
        """Exchange a pairing code for an owner credential (meter_id)."""


class HTTPPairingClient(PairingClient):
    """Calls the virtual-smart-meter service's pairing endpoint.

    Expects METER_SERVICE_URL (+ optional METER_SERVICE_TOKEN). The service
    returns {meter_id} on success or a 4xx with {reason} on failure.
    """

    async def exchange(self, pairing_code: str, profile_id: str) -> PairingResult:
        import httpx

        base = os.environ["METER_SERVICE_URL"].rstrip("/")
        headers = {}
        token = os.getenv("METER_SERVICE_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{base}/pairings/exchange",
                json={"pairing_code": pairing_code, "profile_id": profile_id},
                headers=headers,
            )
        if resp.status_code == 200:
            data = resp.json()
            return PairingResult(ok=True, meter_id=str(data["meter_id"]))
        reason = "invalid"
        try:
            reason = resp.json().get("reason", "invalid")
        except Exception:
            pass
        return PairingResult(ok=False, reason=reason)


class SimulatedPairingClient(PairingClient):
    """Deterministic stand-in for local/dev when METER_SERVICE_URL is unset.

    Encodes outcomes in the code prefix so the flow is exercisable end-to-end
    without the real service:
      - "EXPIRED-..."  → expired
      - "CLAIMED-..."  → already_claimed
      - "BADCODE"/empty/short → invalid
      - otherwise      → success, meter_id derived from the code
    """

    async def exchange(self, pairing_code: str, profile_id: str) -> PairingResult:
        code = (pairing_code or "").strip().upper()
        if not code or len(code) < 6 or code == "BADCODE":
            return PairingResult(ok=False, reason="invalid")
        if code.startswith("EXPIRED"):
            return PairingResult(ok=False, reason="expired")
        if code.startswith("CLAIMED"):
            return PairingResult(ok=False, reason="already_claimed")
        return PairingResult(ok=True, meter_id=f"METER-{code}")


# --- Data layer --------------------------------------------------------------

class BindingStore(ABC):
    @abstractmethod
    async def get_profile_binding(self, profile_id: str) -> dict[str, Any] | None:
        """Return {application_status?, meter_binding_status, meter_id} or None.
        application_status comes from the seller's application record."""

    @abstractmethod
    async def set_binding_status(
        self, profile_id: str, status: str, meter_id: str | None = None
    ) -> None:
        ...

    @abstractmethod
    async def meter_id_taken(self, meter_id: str, exclude_profile_id: str) -> bool:
        """True if another profile already holds this meter_id."""

    @abstractmethod
    async def record_attempt(self, profile_id: str, at_epoch: float) -> None:
        ...

    @abstractmethod
    async def count_recent_attempts(
        self, profile_id: str, since_epoch: float
    ) -> int:
        ...


class SupabaseBindingStore(BindingStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_profile_binding(self, profile_id: str) -> dict[str, Any] | None:
        prof = (
            self._client.table("profiles")
            .select("id, meter_binding_status, meter_id")
            .eq("id", profile_id)
            .limit(1)
            .execute()
        )
        if not prof.data:
            return None
        row = dict(prof.data[0])
        app = (
            self._client.table("seller_applications")
            .select("application_status")
            .eq("profile_id", profile_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        row["application_status"] = (
            app.data[0]["application_status"] if app.data else None
        )
        return row

    async def set_binding_status(
        self, profile_id: str, status: str, meter_id: str | None = None
    ) -> None:
        updates: dict[str, Any] = {"meter_binding_status": status}
        if meter_id is not None:
            updates["meter_id"] = meter_id
        self._client.table("profiles").update(updates).eq("id", profile_id).execute()

    async def meter_id_taken(self, meter_id: str, exclude_profile_id: str) -> bool:
        res = (
            self._client.table("profiles")
            .select("id")
            .eq("meter_id", meter_id)
            .neq("id", exclude_profile_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)

    async def record_attempt(self, profile_id: str, at_epoch: float) -> None:
        self._client.table("meter_pairing_attempts").insert(
            {"profile_id": profile_id, "attempted_at_epoch": at_epoch}
        ).execute()

    async def count_recent_attempts(
        self, profile_id: str, since_epoch: float
    ) -> int:
        res = (
            self._client.table("meter_pairing_attempts")
            .select("id", count="exact")
            .eq("profile_id", profile_id)
            .gte("attempted_at_epoch", since_epoch)
            .execute()
        )
        return res.count or 0


_store: BindingStore | None = None
_client: PairingClient | None = None


def _get_store() -> BindingStore:
    global _store
    if _store is None:
        _store = SupabaseBindingStore()
    return _store


def _get_client() -> PairingClient:
    global _client
    if _client is None:
        _client = (
            HTTPPairingClient()
            if os.getenv("METER_SERVICE_URL")
            else SimulatedPairingClient()
        )
    return _client


def set_store(store: BindingStore | None) -> None:
    global _store
    _store = store


def set_client(client: PairingClient | None) -> None:
    global _client
    _client = client


def _now() -> float:
    return time.time()


# --- Operations --------------------------------------------------------------

_REASON_MESSAGES = {
    "invalid": "The pairing code is invalid.",
    "expired": "The pairing code has expired. Ask the operator to reissue one.",
    "already_claimed": "This meter has already been claimed by another account.",
}


async def get_binding(profile_id: str) -> dict[str, Any]:
    binding = await _get_store().get_profile_binding(profile_id)
    if binding is None:
        raise MeterBindingError(404, "Profile not found")
    return {
        "meter_binding_status": binding.get("meter_binding_status", "unbound"),
        "meter_id": binding.get("meter_id"),
    }


async def submit_pairing_code(profile_id: str, pairing_code: str) -> dict[str, Any]:
    """Drive the binding state machine for one pairing-code submission.

    Returns {meter_binding_status, meter_id?, reason?}. Raises
    MeterBindingError for precondition failures (not-approved, already bound,
    rate-limited).
    """
    store = _get_store()
    binding = await store.get_profile_binding(profile_id)
    if binding is None:
        raise MeterBindingError(404, "Profile not found")

    # Precondition: identity approved (spec §3.2 — binding only reachable after
    # identity_approved).
    if binding.get("application_status") != "identity_approved":
        raise MeterBindingError(
            409, "Meter binding requires an approved identity application"
        )

    # `bound` is terminal — no rebind/transfer (spec §3.2, §6).
    if binding.get("meter_binding_status") == "bound":
        raise MeterBindingError(
            409, "A meter is already bound to this profile and cannot be changed"
        )

    if not pairing_code or not pairing_code.strip():
        raise MeterBindingError(422, "A pairing code is required")

    # Rate limit the exchange attempts (spec §4).
    now = _now()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    recent = await store.count_recent_attempts(profile_id, window_start)
    if recent >= RATE_LIMIT_MAX_ATTEMPTS:
        raise MeterBindingError(
            429,
            "Too many pairing attempts. Wait a few minutes before trying again.",
        )
    await store.record_attempt(profile_id, now)

    # Move to pairing_pending for the duration of the exchange.
    await store.set_binding_status(profile_id, "pairing_pending")

    result = await _get_client().exchange(pairing_code.strip(), profile_id)

    if not result.ok or not result.meter_id:
        reason = result.reason or "invalid"
        await store.set_binding_status(profile_id, "binding_failed")
        return {
            "meter_binding_status": "binding_failed",
            "reason": _REASON_MESSAGES.get(reason, _REASON_MESSAGES["invalid"]),
            "reason_code": reason,
        }

    # API-level uniqueness check before we try to write (friendly message; the
    # DB unique constraint is the ultimate backstop against a race).
    if await store.meter_id_taken(result.meter_id, profile_id):
        await store.set_binding_status(profile_id, "binding_failed")
        return {
            "meter_binding_status": "binding_failed",
            "reason": _REASON_MESSAGES["already_claimed"],
            "reason_code": "already_claimed",
        }

    try:
        await store.set_binding_status(profile_id, "bound", meter_id=result.meter_id)
    except Exception:
        # Unique-constraint violation from a concurrent bind of the same meter.
        await store.set_binding_status(profile_id, "binding_failed")
        return {
            "meter_binding_status": "binding_failed",
            "reason": _REASON_MESSAGES["already_claimed"],
            "reason_code": "already_claimed",
        }

    # Bridge to ingestion: register the bound meter as the seller's device so
    # /meter-readings can authenticate its pushes. The plaintext device token
    # is returned exactly once (stored only as a hash) — in the real
    # architecture the virtual-smart-meter service holds this credential; with
    # the simulated client it's surfaced to the seller for their device/sim.
    # Best-effort: a registration failure must not unwind a successful bind.
    device_token = None
    try:
        from app.services import meter as meter_service

        reg = await meter_service.register_device(profile_id, result.meter_id)
        device_token = reg.get("device_token")
    except Exception:
        logger.exception(
            "Device auto-registration failed after binding meter %s",
            result.meter_id,
        )

    return {
        "meter_binding_status": "bound",
        "meter_id": result.meter_id,
        "device_token": device_token,
    }
