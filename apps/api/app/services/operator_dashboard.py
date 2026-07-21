"""Operator dashboard data service.

Read-side aggregation for the operator dashboard (Phase 7):
- Live feed of AI recommendations (auto-approved shown resolved).
- Pool status backing the import/export panel.
- Distribution view: aggregate kWh supplied to the community by seller.
- Aggregate stats backing the profitability claim.

Operator ACTIONS (approve/adjust/reject) stay in exception_queue — this
module never mutates contributions.

Spread/uplift math uses the active operator_policy row, whose values are
PLACEHOLDERS per the architecture doc's "Open items" (feed-in tariff 0.10,
operator margin 5%).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# PLACEHOLDER fallbacks, mirroring the seeded operator_policy row. Used only
# if the policy table is empty.
FALLBACK_FEED_IN_TARIFF = 0.10
FALLBACK_OPERATOR_MARGIN_PCT = 5.0


@dataclass
class FeedItem:
    id: str
    seller_id: str
    kwh_contributed: float
    ai_recommended_price: float
    final_approved_price: float
    approval_type: str | None
    approval_reason: str | None
    status: str
    direction: str
    deviation_reason: str | None
    created_at: str


@dataclass
class PoolStatus:
    total_kwh_contributed: float
    current_absorption_kwh: float
    absorption_limit_kwh: float
    # Pending import/export recommendations awaiting an operator decision.
    pending_import_export: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DistributionItem:
    seller_id: str
    total_kwh: float
    contribution_count: int


@dataclass
class AggregateStats:
    total_kwh_settled: float
    total_payouts: float
    total_spread_captured: float
    average_uplift_percentage: float
    feed_in_tariff_reference: float
    settled_count: int


class OperatorDashboardStore(ABC):
    @abstractmethod
    async def get_feed(self, limit: int = 50) -> list[FeedItem]:
        ...

    @abstractmethod
    async def get_pool_status(self) -> PoolStatus:
        ...

    @abstractmethod
    async def get_distribution(self) -> list[DistributionItem]:
        ...

    @abstractmethod
    async def get_aggregate_stats(self) -> AggregateStats:
        ...


def _row_to_feed_item(row: dict[str, Any]) -> FeedItem:
    return FeedItem(
        id=str(row["id"]),
        seller_id=str(row.get("seller_id", "")),
        kwh_contributed=float(row.get("kwh_contributed", 0)),
        ai_recommended_price=float(row.get("ai_recommended_price", 0)),
        final_approved_price=float(row.get("final_approved_price", 0)),
        approval_type=row.get("approval_type"),
        approval_reason=row.get("approval_reason"),
        status=row.get("status", ""),
        direction=row.get("direction", "local_pool"),
        deviation_reason=row.get("review_reason"),
        created_at=row.get("created_at", ""),
    )


def compute_stats(
    settled_rows: list[dict[str, Any]],
    feed_in_tariff: float,
    operator_margin_pct: float,
) -> AggregateStats:
    """Aggregate profitability numbers from settled contributions.

    - average_uplift_percentage: mean of (final price − tariff) / tariff over
      settled rows — the seller-side uplift the payout rule promises.
    - total_spread_captured: operator margin % of community billing — settled
      energy valued at final approved prices — per the PLACEHOLDER
      profitability rule. Computed from final_approved_price so the spread
      responds to operator price decisions (adjusts), unlike a tariff basis.
    """
    total_kwh = 0.0
    total_payouts = 0.0
    total_billed_value = 0.0
    uplift_sum = 0.0

    for row in settled_rows:
        kwh = float(row.get("kwh_contributed", 0))
        price = float(row.get("final_approved_price", 0))
        total_kwh += kwh
        total_payouts += float(row.get("payout_amount", 0))
        total_billed_value += price * kwh
        if feed_in_tariff > 0:
            uplift_sum += (price - feed_in_tariff) / feed_in_tariff * 100

    count = len(settled_rows)
    return AggregateStats(
        total_kwh_settled=round(total_kwh, 4),
        total_payouts=round(total_payouts, 6),
        total_spread_captured=round(
            total_billed_value * operator_margin_pct / 100, 6
        ),
        average_uplift_percentage=round(uplift_sum / count, 4) if count else 0.0,
        feed_in_tariff_reference=feed_in_tariff,
        settled_count=count,
    )


class SupabaseOperatorDashboardStore(OperatorDashboardStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    def _active_policy(self) -> tuple[float, float]:
        result = (
            self._client.table("operator_policy")
            .select("feed_in_tariff_reference, operator_margin_percentage")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if result.data:
            row = result.data[0]
            return (
                float(row["feed_in_tariff_reference"]),
                float(row["operator_margin_percentage"]),
            )
        return FALLBACK_FEED_IN_TARIFF, FALLBACK_OPERATOR_MARGIN_PCT

    async def get_feed(self, limit: int = 50) -> list[FeedItem]:
        result = (
            self._client.table("contributions")
            .select(
                "id, seller_id, kwh_contributed, ai_recommended_price, "
                "final_approved_price, approval_type, approval_reason, "
                "status, direction, review_reason, created_at"
            )
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [_row_to_feed_item(row) for row in result.data or []]

    async def get_pool_status(self) -> PoolStatus:
        pool_result = (
            self._client.table("community_pool")
            .select("total_kwh_contributed, current_absorption_kwh, absorption_limit_kwh")
            .limit(1)
            .execute()
        )
        pool_row = pool_result.data[0] if pool_result.data else {}

        pending_result = (
            self._client.table("contributions")
            .select(
                "id, seller_id, kwh_contributed, ai_recommended_price, "
                "direction, review_reason, created_at"
            )
            .eq("status", "needs_review")
            .in_("direction", ["import", "export"])
            .order("created_at", desc=True)
            .execute()
        )

        return PoolStatus(
            total_kwh_contributed=float(pool_row.get("total_kwh_contributed", 0)),
            current_absorption_kwh=float(pool_row.get("current_absorption_kwh", 0)),
            absorption_limit_kwh=float(pool_row.get("absorption_limit_kwh", 0)),
            pending_import_export=[
                {
                    "id": str(row["id"]),
                    "seller_id": str(row.get("seller_id", "")),
                    "kwh": float(row.get("kwh_contributed", 0)),
                    "ai_recommended_price": float(row.get("ai_recommended_price", 0)),
                    "direction": row.get("direction", ""),
                    "deviation_reason": row.get("review_reason"),
                    "created_at": row.get("created_at", ""),
                }
                for row in pending_result.data or []
            ],
        )

    async def get_distribution(self) -> list[DistributionItem]:
        # Supabase's PostgREST client has no group-by; aggregate in Python.
        # Fine at current scale; move to an RPC/view if volume grows.
        # Settled-only: "kWh delivered to the community pool" is the canonical
        # contribution metric (architecture doc, seller dashboard section) and
        # must match the seller dashboard's cumulative_kwh and the cNFT
        # badge thresholds.
        result = (
            self._client.table("contributions")
            .select("seller_id, kwh_contributed, direction, status")
            .eq("status", "settled")
            .execute()
        )
        totals: dict[str, DistributionItem] = {}
        for row in result.data or []:
            if row.get("direction", "local_pool") != "local_pool":
                continue
            seller_id = str(row.get("seller_id", ""))
            item = totals.get(seller_id)
            if item is None:
                item = DistributionItem(seller_id=seller_id, total_kwh=0.0, contribution_count=0)
                totals[seller_id] = item
            item.total_kwh = round(item.total_kwh + float(row.get("kwh_contributed", 0)), 4)
            item.contribution_count += 1
        return sorted(totals.values(), key=lambda i: i.total_kwh, reverse=True)

    async def get_aggregate_stats(self) -> AggregateStats:
        tariff, margin_pct = self._active_policy()
        result = (
            self._client.table("contributions")
            .select("kwh_contributed, final_approved_price, payout_amount")
            .eq("status", "settled")
            .execute()
        )
        return compute_stats(result.data or [], tariff, margin_pct)


_store: OperatorDashboardStore | None = None


def _get_store() -> OperatorDashboardStore:
    global _store
    if _store is None:
        _store = SupabaseOperatorDashboardStore()
    return _store


def set_store(store: OperatorDashboardStore | None) -> None:
    global _store
    _store = store


async def get_feed(limit: int = 50) -> list[FeedItem]:
    return await _get_store().get_feed(limit)


async def get_pool_status() -> PoolStatus:
    return await _get_store().get_pool_status()


async def get_distribution() -> list[DistributionItem]:
    return await _get_store().get_distribution()


async def get_aggregate_stats() -> AggregateStats:
    return await _get_store().get_aggregate_stats()
