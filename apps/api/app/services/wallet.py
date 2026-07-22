"""Wallet address helpers for GridRight API.

Fetches wallet_address from profiles via the Supabase service role client.
Used to gate seller listing and operator settlement actions.
"""
from __future__ import annotations

import os
from functools import lru_cache

from app.auth import UserProfile


@lru_cache(maxsize=1)
def _supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )


async def get_wallet_address(user_id: str) -> str | None:
    """Return the wallet_address for a profile, or None if unset."""
    try:
        result = (
            _supabase()
            .table("profiles")
            .select("wallet_address")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return result.data.get("wallet_address") if result.data else None
    except Exception:
        return None


async def get_active_wallet(user_id: str) -> str | None:
    """Return the wallet_address for a profile ONLY if wallet_status='active'.

    Seller onboarding spec §3.4: profiles that haven't completed the signed
    wallet connect (wallet_status = not_connected) are excluded from
    settlement — readings accumulate, nothing is paid out. Settlement is
    forward-only: readings from before activation are stored but never
    settled retroactively (implementer decision, flagged in the phase report).
    """
    try:
        result = (
            _supabase()
            .table("profiles")
            .select("wallet_address, wallet_status")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if not result.data:
            return None
        if result.data.get("wallet_status") != "active":
            return None
        return result.data.get("wallet_address")
    except Exception:
        return None


async def require_wallet_for_seller_id(seller_id: str) -> str:
    """Raise HTTPException(422) if the seller's wallet is not ACTIVE.

    Used on /recommend, where the surplus signal enters the system by
    seller_id (not an authenticated session). This is the settlement-exclusion
    gate from the onboarding spec §3.4: a seller whose wallet_status is
    not_connected can keep ingesting meter readings, but cannot list surplus
    for settlement. Skipped in test mode.
    """
    import os
    from fastapi import HTTPException
    if os.getenv("SUPABASE_AUTH_TESTING") == "1":
        return "test-wallet-address"
    addr = await get_active_wallet(seller_id)
    if not addr:
        raise HTTPException(
            status_code=422,
            detail="Seller wallet is not active. Complete the signed wallet "
                   "connect before listing surplus.",
        )
    return addr


async def require_wallet(user: UserProfile) -> str:
    """Raise HTTPException(422) if the user has no registered wallet_address.

    Skipped when SUPABASE_AUTH_TESTING=1 (mirrors the auth testing convention)
    so existing tests that don't mock wallet_address continue to pass.
    """
    import os
    from fastapi import HTTPException
    if os.getenv("SUPABASE_AUTH_TESTING") == "1":
        return "test-wallet-address"
    addr = await get_wallet_address(user.id)
    if not addr:
        raise HTTPException(
            status_code=422,
            detail="A registered wallet_address is required. Connect your Phantom wallet first.",
        )
    return addr
