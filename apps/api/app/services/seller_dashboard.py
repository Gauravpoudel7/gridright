from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


class DashboardData:
    surplus_this_period: float
    cumulative_kwh: float
    total_earned: float
    period_start: str
    period_end: str


class PeriodHistoryItem:
    period_start: str
    period_end: str
    kwh_contributed: float
    amount_earned: float
    status: str


class SellerDashboardStore(ABC):
    @abstractmethod
    async def get_dashboard(self, seller_id: str) -> DashboardData:
        ...

    @abstractmethod
    async def get_history(self, seller_id: str) -> list[PeriodHistoryItem]:
        ...


def aggregate_dashboard(rows: list[dict[str, Any]]) -> DashboardData:
    """Aggregate contribution rows (newest first) into dashboard numbers.

    cumulative_kwh is the canonical contribution metric ("kWh delivered to
    the community pool") — settled-only, matching the operator distribution
    view and the future cNFT badge thresholds. Rejected contributions were
    never delivered; pending ones aren't yet. total_earned uses the same
    settled-only scope so every displayed dollar traces to a settlement.

    "This period" reads the newest contribution that wasn't rejected —
    pending/needs_review surplus has been contributed even though it
    hasn't settled yet.
    """
    cumulative_kwh = 0.0
    total_earned = 0.0

    for row in rows:
        if row.get("status") == "settled":
            cumulative_kwh += float(row.get("kwh_contributed", 0))
            total_earned += float(row.get("payout_amount", 0))

    active_rows = [r for r in rows if r.get("status") != "rejected"]

    data = DashboardData()
    data.surplus_this_period = (
        float(active_rows[0].get("kwh_contributed", 0)) if active_rows else 0.0
    )
    data.cumulative_kwh = cumulative_kwh
    data.total_earned = total_earned
    data.period_start = active_rows[0].get("period_start", "") if active_rows else ""
    data.period_end = active_rows[0].get("period_end", "") if active_rows else ""
    return data


class SupabaseSellerDashboardStore(SellerDashboardStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_dashboard(self, seller_id: str) -> DashboardData:
        result = (
            self._client.table("contributions")
            .select("kwh_contributed, payout_amount, period_start, period_end, status")
            .eq("seller_id", seller_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = result.data or []
        return aggregate_dashboard(rows)

    async def get_history(self, seller_id: str) -> list[PeriodHistoryItem]:
        result = (
            self._client.table("contributions")
            .select("period_start, period_end, kwh_contributed, payout_amount, status")
            .eq("seller_id", seller_id)
            .order("period_start", desc=True)
            .execute()
        )
        rows = result.data or []
        items = []
        for row in rows:
            item = PeriodHistoryItem()
            item.period_start = row.get("period_start", "")
            item.period_end = row.get("period_end", "")
            item.kwh_contributed = float(row.get("kwh_contributed", 0))
            item.amount_earned = float(row.get("payout_amount", 0)) if row.get("status") == "settled" else 0.0
            item.status = row.get("status", "")
            items.append(item)
        return items


_store: SellerDashboardStore | None = None


def _get_store() -> SellerDashboardStore:
    global _store
    if _store is None:
        _store = SupabaseSellerDashboardStore()
    return _store


def set_store(store: SellerDashboardStore | None) -> None:
    global _store
    _store = store


async def get_dashboard(seller_id: str) -> DashboardData:
    return await _get_store().get_dashboard(seller_id)


async def get_history(seller_id: str) -> list[PeriodHistoryItem]:
    return await _get_store().get_history(seller_id)
