"""Phase 8 — cNFT contribution milestone badges.

When a seller's cumulative *settled* kwh_contributed crosses a milestone
threshold, mint exactly one Bubblegum cNFT badge for that threshold.

The contribution metric is deliberately the same settled-only cumulative
used by the seller dashboard (see seller_dashboard.aggregate_dashboard)
so the badge thresholds and the dashboard number can never disagree.

Thresholds are PLACEHOLDERS (100 / 500 / 1000 kWh) seeded by migration
20250719000004 — tune later per the architecture doc's "Open items" #4.

Idempotency has two layers:
  1. compute_newly_crossed() only returns thresholds without an existing
     seller_badges row.
  2. The DB unique constraint (seller_id, threshold_kwh) rejects a
     duplicate insert if two settlements race — the loser simply skips.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


class BadgeThreshold:
    threshold_kwh: float
    label: str


class SellerBadge:
    threshold_kwh: float
    label: str
    kwh_at_mint: float
    asset_id: str | None
    tx_signature: str | None
    mint_status: str
    created_at: str


class MintResult:
    asset_id: str | None
    tx_signature: str | None
    ok: bool
    error: str | None


def compute_newly_crossed(
    cumulative_kwh: float,
    thresholds: list[dict[str, Any]],
    already_earned_kwh: set[float],
) -> list[dict[str, Any]]:
    """Pure milestone logic: which active thresholds has this seller crossed
    that don't already have a badge? Returns them lowest-first so a seller
    jumping past several milestones in one settlement earns each in order.
    """
    crossed = [
        t for t in thresholds
        if float(t["threshold_kwh"]) <= cumulative_kwh
        and float(t["threshold_kwh"]) not in already_earned_kwh
    ]
    return sorted(crossed, key=lambda t: float(t["threshold_kwh"]))


class BadgeStore(ABC):
    @abstractmethod
    async def get_active_thresholds(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def get_cumulative_settled_kwh(self, seller_id: str) -> float:
        ...

    @abstractmethod
    async def get_earned_threshold_kwhs(self, seller_id: str) -> set[float]:
        ...

    @abstractmethod
    async def insert_badge(
        self, seller_id: str, threshold_kwh: float, label: str, kwh_at_mint: float
    ) -> str | None:
        """Insert a pending badge row. Returns the row id, or None if the
        unique (seller_id, threshold_kwh) constraint rejected it — i.e. a
        concurrent settlement already minted this threshold."""
        ...

    @abstractmethod
    async def mark_badge_minted(
        self, badge_id: str, asset_id: str | None, tx_signature: str | None, ok: bool
    ) -> None:
        ...

    @abstractmethod
    async def list_badges(self, seller_id: str) -> list[dict[str, Any]]:
        ...


class BadgeMinter(ABC):
    @abstractmethod
    async def mint(self, seller_id: str, label: str, threshold_kwh: float) -> MintResult:
        ...


class SupabaseBadgeStore(BadgeStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_active_thresholds(self) -> list[dict[str, Any]]:
        result = (
            self._client.table("badge_thresholds")
            .select("threshold_kwh, label")
            .eq("is_active", True)
            .execute()
        )
        return result.data or []

    async def get_cumulative_settled_kwh(self, seller_id: str) -> float:
        # Same settled-only scope as seller_dashboard.aggregate_dashboard —
        # the badge metric and the dashboard metric must be one number.
        result = (
            self._client.table("contributions")
            .select("kwh_contributed")
            .eq("seller_id", seller_id)
            .eq("status", "settled")
            .execute()
        )
        return sum(float(r["kwh_contributed"]) for r in (result.data or []))

    async def get_earned_threshold_kwhs(self, seller_id: str) -> set[float]:
        result = (
            self._client.table("seller_badges")
            .select("threshold_kwh")
            .eq("seller_id", seller_id)
            .execute()
        )
        return {float(r["threshold_kwh"]) for r in (result.data or [])}

    async def insert_badge(
        self, seller_id: str, threshold_kwh: float, label: str, kwh_at_mint: float
    ) -> str | None:
        try:
            result = (
                self._client.table("seller_badges")
                .insert({
                    "seller_id": seller_id,
                    "threshold_kwh": threshold_kwh,
                    "label": label,
                    "kwh_at_mint": kwh_at_mint,
                    "mint_status": "pending",
                })
                .execute()
            )
            return result.data[0]["id"]
        except Exception:
            # Unique violation — a concurrent settlement won the race.
            return None

    async def mark_badge_minted(
        self, badge_id: str, asset_id: str | None, tx_signature: str | None, ok: bool
    ) -> None:
        self._client.table("seller_badges").update({
            "asset_id": asset_id,
            "tx_signature": tx_signature,
            "mint_status": "minted" if ok else "failed",
        }).eq("id", badge_id).execute()

    async def list_badges(self, seller_id: str) -> list[dict[str, Any]]:
        result = (
            self._client.table("seller_badges")
            .select("threshold_kwh, label, kwh_at_mint, asset_id, tx_signature, "
                    "mint_status, created_at")
            .eq("seller_id", seller_id)
            .order("threshold_kwh")
            .execute()
        )
        return result.data or []


class BubblegumBadgeMinter(BadgeMinter):
    """Mints via the TS script in programs/gridright/scripts/mint-badge.ts,
    which owns the umi/Bubblegum client. Requires BADGE_TREE_ADDRESS (set by
    setup-badge-tree.ts) and a funded devnet keypair at ~/.config/solana/id.json.
    """

    def __init__(self) -> None:
        self._tree = os.environ["BADGE_TREE_ADDRESS"]
        self._script_dir = os.environ.get(
            "BADGE_SCRIPT_DIR",
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                         "programs", "gridright"),
        )

    async def mint(self, seller_id: str, label: str, threshold_kwh: float) -> MintResult:
        import asyncio
        import json
        import shutil

        result = MintResult()
        # On Windows npx is npx.cmd — exec by resolved path, not bare name
        npx = shutil.which("npx") or "npx"
        proc = await asyncio.create_subprocess_exec(
            npx, "tsx", "scripts/mint-badge.ts",
            "--tree", self._tree,
            "--seller", seller_id,
            "--label", label,
            "--threshold", str(threshold_kwh),
            cwd=self._script_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            result.ok = False
            result.asset_id = None
            result.tx_signature = None
            result.error = stderr.decode(errors="replace")[-500:]
            return result
        # mint-badge.ts prints a single JSON line: {"assetId": ..., "signature": ...}
        out = json.loads(stdout.decode().strip().splitlines()[-1])
        result.ok = True
        result.asset_id = out.get("assetId")
        result.tx_signature = out.get("signature")
        result.error = None
        return result


_store: BadgeStore | None = None
_minter: BadgeMinter | None = None


def _get_store() -> BadgeStore:
    global _store
    if _store is None:
        _store = SupabaseBadgeStore()
    return _store


def _get_minter() -> BadgeMinter:
    global _minter
    if _minter is None:
        _minter = BubblegumBadgeMinter()
    return _minter


def set_store(store: BadgeStore | None) -> None:
    global _store
    _store = store


def set_minter(minter: BadgeMinter | None) -> None:
    global _minter
    _minter = minter


async def check_and_mint(seller_id: str) -> list[dict[str, Any]]:
    """Called after a contribution settles. Mints one badge per newly crossed
    threshold and returns the badges minted in this call (possibly empty).
    Safe to call repeatedly — already-earned thresholds are skipped.
    """
    store = _get_store()

    cumulative = await store.get_cumulative_settled_kwh(seller_id)
    thresholds = await store.get_active_thresholds()
    earned = await store.get_earned_threshold_kwhs(seller_id)

    newly_crossed = compute_newly_crossed(cumulative, thresholds, earned)
    if not newly_crossed:
        return []

    minter = _get_minter()
    minted: list[dict[str, Any]] = []
    for t in newly_crossed:
        threshold_kwh = float(t["threshold_kwh"])
        label = t["label"]
        badge_id = await store.insert_badge(seller_id, threshold_kwh, label, cumulative)
        if badge_id is None:
            continue  # lost a race — the badge already exists
        result = await minter.mint(seller_id, label, threshold_kwh)
        await store.mark_badge_minted(
            badge_id, result.asset_id, result.tx_signature, result.ok
        )
        minted.append({
            "threshold_kwh": threshold_kwh,
            "label": label,
            "kwh_at_mint": cumulative,
            "asset_id": result.asset_id,
            "tx_signature": result.tx_signature,
            "mint_status": "minted" if result.ok else "failed",
        })
    return minted


async def list_badges(seller_id: str) -> list[dict[str, Any]]:
    return await _get_store().list_badges(seller_id)
