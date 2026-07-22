"""30-minute settlement cycles with a roll-forward missed-deadline rule.

Every 30 minutes an external scheduler fires POST /settlements/run (same
SCHEDULER_TOKEN pattern as /forecasts/run). One run:

  1. Closes out the previous batch. Fully paid → 'completed' (normally already
     done at payment time). Otherwise → 'rolled_over': every unpaid item
     carries forward into the new batch with missed_cycles + 1.
  2. Collects fresh eligible contributions — decision-settled, unpaid, not yet
     batched, seller's wallet_status = 'active' (onboarding spec §3.4:
     not-connected sellers accumulate readings but are excluded; settlement is
     forward-only).
  3. Groups per seller, merges carried amounts, creates the new batch due in
     CYCLE_MINUTES.

THE MISSED-DEADLINE RULE:
  * Sellers never lose a payout — unpaid amounts accumulate across cycles.
  * missed_cycles counts consecutive cycles a payout has been due-and-unpaid.
  * At ESCALATION_MISS_THRESHOLD (3 ≈ 90 min) the item and its batch are
    flagged `escalated` — surfaced red on the operator dashboard as requiring
    immediate action. Intake is never paused; the deadline pressures the
    operator, not the sellers.

Wallet snapshots: an item's payout_wallet is fixed at the item's FIRST batch
(spec §3.3 — a wallet change applies from the next cycle only). A carried
item keeps its original wallet even if the seller re-connected mid-cycle;
fresh contributions from after the change settle to the new wallet in their
own item... except a seller can have only one item per batch, so a merged
item keeps the carried (older) wallet — the new wallet takes over once the
backlog clears. Documented trade-off, favors payment continuity.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

CYCLE_MINUTES = 30
ESCALATION_MISS_THRESHOLD = 3


class SettlementCycleError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class SettlementStore(ABC):
    @abstractmethod
    async def get_open_batch(self) -> dict[str, Any] | None:
        """The current 'due' batch (at most one exists), or None."""

    @abstractmethod
    async def get_items(self, batch_id: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def close_batch(
        self, batch_id: str, status: str, completed_at: str | None = None
    ) -> None:
        ...

    @abstractmethod
    async def create_batch(
        self, cycle_start: str, due_at: str, escalated: bool
    ) -> str:
        ...

    @abstractmethod
    async def create_item(self, item: dict[str, Any]) -> str:
        ...

    @abstractmethod
    async def get_eligible_contributions(self) -> list[dict[str, Any]]:
        """Unpaid, decision-settled, unbatched contributions for sellers with
        wallet_status='active'. Each row: {id, seller_id, kwh_contributed,
        payout_amount, payout_wallet (snapshot or current active wallet)}."""

    @abstractmethod
    async def assign_contributions(
        self, contribution_ids: list[str], item_id: str
    ) -> None:
        ...

    @abstractmethod
    async def reassign_item_contributions(
        self, old_item_id: str, new_item_id: str
    ) -> None:
        ...

    @abstractmethod
    async def get_item(self, item_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def mark_item_paid(
        self, item_id: str, tx_signature: str, paid_at: str
    ) -> None:
        """Mark the item paid AND stamp tx_signature on its contributions."""


class SupabaseSettlementStore(SettlementStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_open_batch(self) -> dict[str, Any] | None:
        res = (
            self._client.table("settlement_batches")
            .select("*")
            .eq("status", "due")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    async def get_items(self, batch_id: str) -> list[dict[str, Any]]:
        res = (
            self._client.table("settlement_items")
            .select("*")
            .eq("batch_id", batch_id)
            .execute()
        )
        return res.data or []

    async def close_batch(
        self, batch_id: str, status: str, completed_at: str | None = None
    ) -> None:
        updates: dict[str, Any] = {"status": status}
        if completed_at:
            updates["completed_at"] = completed_at
        self._client.table("settlement_batches").update(updates).eq(
            "id", batch_id
        ).execute()

    async def create_batch(
        self, cycle_start: str, due_at: str, escalated: bool
    ) -> str:
        res = (
            self._client.table("settlement_batches")
            .insert(
                {
                    "cycle_start": cycle_start,
                    "due_at": due_at,
                    "escalated": escalated,
                }
            )
            .execute()
        )
        return res.data[0]["id"]

    async def create_item(self, item: dict[str, Any]) -> str:
        res = self._client.table("settlement_items").insert(item).execute()
        return res.data[0]["id"]

    async def get_eligible_contributions(self) -> list[dict[str, Any]]:
        # Active-wallet sellers only (spec §3.4 settlement exclusion).
        profiles = (
            self._client.table("profiles")
            .select("id, wallet_address")
            .eq("wallet_status", "active")
            .execute()
        )
        active = {p["id"]: p.get("wallet_address") for p in (profiles.data or [])}
        if not active:
            return []
        rows = (
            self._client.table("contributions")
            .select("id, seller_id, kwh_contributed, payout_amount, payout_wallet")
            .eq("status", "settled")
            .is_("tx_signature", "null")
            .is_("settlement_item_id", "null")
            .in_("seller_id", list(active.keys()))
            .execute()
        )
        out = []
        for row in rows.data or []:
            out.append(
                {
                    "id": row["id"],
                    "seller_id": row["seller_id"],
                    "kwh_contributed": float(row["kwh_contributed"]),
                    "payout_amount": float(row["payout_amount"]),
                    # Prefer the decision-time snapshot; fall back to the
                    # seller's current active wallet for pre-snapshot rows.
                    "payout_wallet": row.get("payout_wallet")
                    or active.get(row["seller_id"]),
                }
            )
        return out

    async def assign_contributions(
        self, contribution_ids: list[str], item_id: str
    ) -> None:
        if not contribution_ids:
            return
        self._client.table("contributions").update(
            {"settlement_item_id": item_id}
        ).in_("id", contribution_ids).execute()

    async def reassign_item_contributions(
        self, old_item_id: str, new_item_id: str
    ) -> None:
        self._client.table("contributions").update(
            {"settlement_item_id": new_item_id}
        ).eq("settlement_item_id", old_item_id).execute()

    async def get_item(self, item_id: str) -> dict[str, Any] | None:
        res = (
            self._client.table("settlement_items")
            .select("*")
            .eq("id", item_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    async def mark_item_paid(
        self, item_id: str, tx_signature: str, paid_at: str
    ) -> None:
        self._client.table("settlement_items").update(
            {"paid": True, "tx_signature": tx_signature, "paid_at": paid_at}
        ).eq("id", item_id).execute()
        self._client.table("contributions").update(
            {"tx_signature": tx_signature}
        ).eq("settlement_item_id", item_id).execute()


_store: SettlementStore | None = None


def _get_store() -> SettlementStore:
    global _store
    if _store is None:
        _store = SupabaseSettlementStore()
    return _store


def set_store(store: SettlementStore | None) -> None:
    global _store
    _store = store


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Operations --------------------------------------------------------------

async def run_settlement_cycle() -> dict[str, Any]:
    """One 30-minute cycle: roll the previous batch, batch fresh payouts."""
    store = _get_store()
    now = _now()
    now_iso = now.isoformat()

    # Per-seller accumulator: seller_id -> merged payout line.
    merged: dict[str, dict[str, Any]] = {}
    rolled_over = 0

    prev = await store.get_open_batch()
    if prev is not None:
        items = await store.get_items(prev["id"])
        unpaid = [i for i in items if not i.get("paid")]
        if not unpaid:
            # Everything was paid but the batch wasn't closed (e.g. the last
            # payment raced the run) — complete it now.
            await store.close_batch(prev["id"], "completed", completed_at=now_iso)
        else:
            # MISSED DEADLINE: carry every unpaid item forward, +1 miss each.
            await store.close_batch(prev["id"], "rolled_over")
            for item in unpaid:
                rolled_over += 1
                merged[item["seller_id"]] = {
                    "seller_id": item["seller_id"],
                    "payout_wallet": item["payout_wallet"],
                    "total_kwh": float(item["total_kwh"]),
                    "total_amount": float(item["total_amount"]),
                    "contribution_count": int(item["contribution_count"]),
                    "missed_cycles": int(item.get("missed_cycles", 0)) + 1,
                    "carried_from_item": item["id"],
                    "contribution_ids": [],
                }

    # Fresh eligible contributions, grouped per seller.
    for row in await store.get_eligible_contributions():
        line = merged.setdefault(
            row["seller_id"],
            {
                "seller_id": row["seller_id"],
                "payout_wallet": row["payout_wallet"],
                "total_kwh": 0.0,
                "total_amount": 0.0,
                "contribution_count": 0,
                "missed_cycles": 0,
                "carried_from_item": None,
                "contribution_ids": [],
            },
        )
        line["total_kwh"] += row["kwh_contributed"]
        line["total_amount"] += row["payout_amount"]
        line["contribution_count"] += 1
        line["contribution_ids"].append(row["id"])

    if not merged:
        return {
            "batch_id": None,
            "skipped": True,
            "reason": "no eligible payouts",
            "rolled_over": 0,
            "escalated": 0,
        }

    escalated_count = sum(
        1 for l in merged.values()
        if l["missed_cycles"] >= ESCALATION_MISS_THRESHOLD
    )
    batch_id = await store.create_batch(
        cycle_start=now_iso,
        due_at=(now + timedelta(minutes=CYCLE_MINUTES)).isoformat(),
        escalated=escalated_count > 0,
    )

    for line in merged.values():
        item_id = await store.create_item(
            {
                "batch_id": batch_id,
                "seller_id": line["seller_id"],
                "payout_wallet": line["payout_wallet"],
                "total_kwh": round(line["total_kwh"], 6),
                "total_amount": round(line["total_amount"], 6),
                "contribution_count": line["contribution_count"],
                "missed_cycles": line["missed_cycles"],
                "escalated": line["missed_cycles"] >= ESCALATION_MISS_THRESHOLD,
            }
        )
        if line["carried_from_item"]:
            await store.reassign_item_contributions(
                line["carried_from_item"], item_id
            )
        await store.assign_contributions(line["contribution_ids"], item_id)

    return {
        "batch_id": batch_id,
        "skipped": False,
        "item_count": len(merged),
        "total_amount": round(sum(l["total_amount"] for l in merged.values()), 6),
        "rolled_over": rolled_over,
        "escalated": escalated_count,
        "due_at": (now + timedelta(minutes=CYCLE_MINUTES)).isoformat(),
    }


async def get_due_settlements() -> dict[str, Any]:
    """Current due batch + payout lines, for the operator dashboard."""
    store = _get_store()
    batch = await store.get_open_batch()
    if batch is None:
        return {"batch": None, "items": []}
    items = await store.get_items(batch["id"])
    return {
        "batch": {
            "id": batch["id"],
            "cycle_start": batch["cycle_start"],
            "due_at": batch["due_at"],
            "escalated": batch.get("escalated", False),
        },
        "items": [
            {
                "id": i["id"],
                "seller_id": i["seller_id"],
                "payout_wallet": i["payout_wallet"],
                "total_kwh": float(i["total_kwh"]),
                "total_amount": float(i["total_amount"]),
                "contribution_count": int(i["contribution_count"]),
                "missed_cycles": int(i.get("missed_cycles", 0)),
                "escalated": bool(i.get("escalated")),
                "paid": bool(i.get("paid")),
                "tx_signature": i.get("tx_signature"),
            }
            for i in items
        ],
    }


async def record_item_paid(item_id: str, tx_signature: str) -> dict[str, Any]:
    """Record the operator's on-chain payment for one payout line. When the
    last unpaid item in the batch is recorded, the batch completes."""
    if not tx_signature or not tx_signature.strip():
        raise SettlementCycleError(422, "tx_signature is required")

    store = _get_store()
    item = await store.get_item(item_id)
    if item is None:
        raise SettlementCycleError(404, "Settlement item not found")
    if item.get("paid"):
        raise SettlementCycleError(409, "Settlement item is already paid")

    now_iso = _now().isoformat()
    await store.mark_item_paid(item_id, tx_signature.strip(), now_iso)

    batch_id = item["batch_id"]
    remaining = [
        i for i in await store.get_items(batch_id)
        if not i.get("paid") and i["id"] != item_id
    ]
    if not remaining:
        await store.close_batch(batch_id, "completed", completed_at=now_iso)

    return {
        "item_id": item_id,
        "paid": True,
        "batch_completed": not remaining,
    }
