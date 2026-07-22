"""Password-change gate + change-password operation (spec §2, §4).

On `identity_approved` the operator flow creates the auth user with a temp
password and sets `must_change_password = true` on the profile. Until the
seller changes it, every seller endpoint (dashboard, meter binding, wallet
connect, ...) is blocked server-side via the `get_password_changed_seller`
dependency in app.auth — the ONLY reachable seller route is the
change-password endpoint itself.

Store is swappable per the repo pattern. In test mode (SUPABASE_AUTH_TESTING=1)
with no store injected the gate is OPEN so the existing suite runs unchanged;
the dedicated gate tests inject an in-memory store to exercise the real check.

Security (spec §4): the temp password is never logged; the new password goes
straight to the Supabase auth admin API and nowhere else.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod


MIN_PASSWORD_LENGTH = 8


class PasswordChangeError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class PasswordGateStore(ABC):
    @abstractmethod
    async def get_must_change_password(self, profile_id: str) -> bool:
        ...

    @abstractmethod
    async def change_password(self, profile_id: str, new_password: str) -> None:
        """Set the new password via the auth admin API AND clear the flag."""


class SupabasePasswordGateStore(PasswordGateStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_must_change_password(self, profile_id: str) -> bool:
        res = (
            self._client.table("profiles")
            .select("must_change_password")
            .eq("id", profile_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            # Unknown profile → fail closed: the gate treats it as unchanged.
            return True
        return bool(res.data[0].get("must_change_password"))

    async def change_password(self, profile_id: str, new_password: str) -> None:
        # Password first, then the flag: if the update fails the gate stays
        # closed rather than being cleared against the old temp password.
        self._client.auth.admin.update_user_by_id(
            profile_id, {"password": new_password}
        )
        self._client.table("profiles").update(
            {"must_change_password": False}
        ).eq("id", profile_id).execute()


_store: PasswordGateStore | None = None


def _get_store() -> PasswordGateStore | None:
    global _store
    if _store is None:
        if os.getenv("SUPABASE_AUTH_TESTING") == "1":
            # Test mode, nothing injected: gate open (see module docstring).
            return None
        _store = SupabasePasswordGateStore()
    return _store


def set_store(store: PasswordGateStore | None) -> None:
    global _store
    _store = store


async def must_change_password(profile_id: str) -> bool:
    store = _get_store()
    if store is None:
        return False
    return await store.get_must_change_password(profile_id)


async def change_password(profile_id: str, new_password: str) -> None:
    """Validate and set the seller's new password, clearing the gate."""
    if not new_password or len(new_password) < MIN_PASSWORD_LENGTH:
        raise PasswordChangeError(
            422, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    store = _get_store()
    if store is None:
        return
    await store.change_password(profile_id, new_password)
