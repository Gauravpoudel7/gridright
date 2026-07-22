"""Meter readings → contributions bridge.

Smart-meter readings land in meter_readings as raw telemetry. Nothing about a
raw reading is money yet: contributions (the rows the settlement cycle batches
and the operator pays) are created by the recommend → policy-check pipeline.
This service is the missing link: each settlement run first sweeps unaggregated
readings, sums grid_export_kwh per seller, and pushes each seller's total
through the SAME pricing pipeline as POST /recommend — auto-approved totals
become settled contributions immediately; out-of-band prices land in the
operator review queue exactly like any other surplus signal.

Swept readings are flagged `aggregated` so surplus is never double-counted.
Readings are marked aggregated even when the total export is zero (nothing to
price) — they've been considered.

Anti-noise threshold: a seller's accumulated export only goes to the operator
once it reaches MIN_AGGREGATION_KWH. Below that, the readings are left unswept
and keep accumulating across cycles — so the review queue holds one line per
seller with MEANINGFUL surplus, not one per active seller per cycle.

Store-ABC pattern as everywhere else (Supabase in prod, dict in tests).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.services.exception_queue import (
    add as queue_add,
    add_auto_approved as queue_add_auto_approved,
)
from app.services.policy_checker import (
    PolicyConfig,
    PriceRecommendation,
    check as policy_check,
)
from app.services.recommender import (
    FleetContext,
    PoolState,
    RecommendationInput,
    recommend,
)

logger = logging.getLogger(__name__)

# A seller's accumulated grid export must reach this before it is priced and
# sent to the operator. Sub-threshold surplus carries forward to later cycles.
MIN_AGGREGATION_KWH = 0.5

# Same PLACEHOLDER policy the /recommend endpoint uses — one pricing policy,
# two entry points.
POLICY = PolicyConfig(
    band_width_percentage=5,
    pool_capacity_limit_kwh=10000,
    seller_uplift_percentage=15,
    operator_margin_percentage=5,
    feed_in_tariff_reference=0.10,
)


class AggregationStore(ABC):
    @abstractmethod
    async def get_unaggregated(self) -> list[dict[str, Any]]:
        """All unswept readings: [{id, seller_id, grid_export_kwh}]."""

    @abstractmethod
    async def mark_aggregated(self, reading_ids: list[str]) -> None:
        ...

    @abstractmethod
    async def get_pool_state(self) -> dict[str, Any] | None:
        """{current_absorption_kwh, absorption_limit_kwh} of the community
        pool, or None if no pool exists."""


class SupabaseAggregationStore(AggregationStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_unaggregated(self) -> list[dict[str, Any]]:
        res = (
            self._client.table("meter_readings")
            .select("id, seller_id, grid_export_kwh")
            .eq("aggregated", False)
            .limit(5000)
            .execute()
        )
        return list(res.data or [])

    async def mark_aggregated(self, reading_ids: list[str]) -> None:
        if not reading_ids:
            return
        self._client.table("meter_readings").update({"aggregated": True}).in_(
            "id", reading_ids
        ).execute()

    async def get_pool_state(self) -> dict[str, Any] | None:
        res = (
            self._client.table("community_pool")
            .select("current_absorption_kwh, absorption_limit_kwh")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None


_store: AggregationStore | None = None


def _get_store() -> AggregationStore:
    global _store
    if _store is None:
        _store = SupabaseAggregationStore()
    return _store


def set_store(store: AggregationStore | None) -> None:
    global _store
    _store = store


async def run_aggregation() -> dict[str, Any]:
    """Sweep unaggregated readings into contributions. Returns a summary:
    {readings, sellers, contributions, needs_review, carried_forward}."""
    store = _get_store()
    readings = await store.get_unaggregated()
    if not readings:
        return {
            "readings": 0,
            "sellers": 0,
            "contributions": 0,
            "needs_review": 0,
            "carried_forward": 0,
        }

    pool_row = await store.get_pool_state() or {}
    pool = PoolState(
        current_absorption_kwh=float(pool_row.get("current_absorption_kwh", 0.0)),
        absorption_limit_kwh=float(pool_row.get("absorption_limit_kwh", 10000.0)),
        current_consumption_kwh=0.0,
    )

    # Optional fleet nudge, same defensive posture as the /recommend endpoint.
    fleet = None
    try:
        from app.services.fleet import get_net_position_kwh

        net = await get_net_position_kwh()
        if net is not None:
            fleet = FleetContext(net_position_kwh=net)
    except Exception:
        fleet = None

    by_seller: dict[str, dict[str, Any]] = {}
    for r in readings:
        line = by_seller.setdefault(
            r["seller_id"], {"total_kwh": 0.0, "reading_ids": []}
        )
        line["total_kwh"] += float(r.get("grid_export_kwh") or 0.0)
        line["reading_ids"].append(r["id"])

    now_time = datetime.now(timezone.utc).time().replace(second=0, microsecond=0)
    contributions = 0
    needs_review = 0
    carried_forward = 0

    for seller_id, line in by_seller.items():
        total = round(line["total_kwh"], 6)
        if total <= 0:
            # Nothing exported — considered, nothing to price.
            await store.mark_aggregated(line["reading_ids"])
            continue

        if total < MIN_AGGREGATION_KWH:
            # Real but sub-threshold surplus: leave the readings UNSWEPT so they
            # keep accumulating across cycles and reach the operator only once
            # they're worth a review-queue line. Nothing priced or marked now.
            carried_forward += 1
            continue

        try:
            rec = await recommend(
                RecommendationInput(
                    seller_surplus_kwh=total,
                    time_of_day=now_time,
                    pool=pool,
                    fleet=fleet,
                )
            )
            result = policy_check(
                PriceRecommendation(
                    recommended_price=rec.recommended_price,
                    recommended_absorption_kwh=rec.recommended_absorption_kwh,
                    direction=rec.direction,
                ),
                POLICY,
            )
            if result.decision == "needs_review":
                await queue_add(
                    seller_id=seller_id,
                    kwh_contributed=total,
                    ai_recommended_price=rec.recommended_price,
                    recommended_absorption_kwh=rec.recommended_absorption_kwh,
                    deviation_reason=result.deviation_reason or "",
                    direction=rec.direction,
                    model_version=rec.model_used,
                )
                needs_review += 1
            else:
                await queue_add_auto_approved(
                    seller_id=seller_id,
                    kwh_contributed=total,
                    ai_recommended_price=rec.recommended_price,
                    direction=rec.direction,
                    model_version=rec.model_used,
                )
                contributions += 1
        except Exception:
            # Leave this seller's readings unswept — they'll be retried on the
            # next cycle rather than silently dropped.
            logger.exception(
                "Meter aggregation failed for seller %s; will retry", seller_id
            )
            continue

        await store.mark_aggregated(line["reading_ids"])

    return {
        "readings": len(readings),
        "sellers": len(by_seller),
        "contributions": contributions,
        "needs_review": needs_review,
        "carried_forward": carried_forward,
    }
