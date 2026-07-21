"""Operator fleet view: aggregated supply + demand outlook (Phase 4).

Aggregates per-seller surplus_forecasts (Phase 3) into a fleet-wide expected
surplus curve with a confidence band, subtracts an expected-demand signal to
give a NET position (surplus vs shortfall), flags sellers whose forecast
accuracy has drifted, and produces a short natural-language outlook reusing
the recommender's LLM-or-fallback pattern (no second LLM integration).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.demand import get_signal as get_demand_signal

# PLACEHOLDER thresholds — tune later.
FLEET_HORIZON_HOURS = 24
# A seller whose mean absolute accuracy delta over recent scored forecasts
# exceeds this (kWh) is flagged as drifted (bad forecast / suspect meter).
ACCURACY_DRIFT_THRESHOLD_KWH = 1.5
MIN_SCORED_FOR_DRIFT = 3  # need at least this many scored forecasts to judge


@dataclass
class HourlyOutlook:
    forecast_for: str
    predicted_surplus_kwh: float
    # Confidence band: predicted ± (1 - mean confidence) * predicted.
    lower_kwh: float
    upper_kwh: float
    expected_demand_kwh: float
    net_position_kwh: float  # supply - demand (negative = shortfall)


@dataclass
class SellerOutlook:
    seller_id: str
    total_predicted_kwh: float
    mean_confidence: float


@dataclass
class DriftFlag:
    seller_id: str
    mean_abs_delta_kwh: float
    scored_count: int


@dataclass
class FleetOutlook:
    horizon_hours: int
    total_predicted_surplus_kwh: float
    total_expected_demand_kwh: float
    net_position_kwh: float
    hourly: list[HourlyOutlook] = field(default_factory=list)
    per_seller: list[SellerOutlook] = field(default_factory=list)
    drift_flags: list[DriftFlag] = field(default_factory=list)
    summary: str = ""


class FleetStore(ABC):
    @abstractmethod
    async def get_forecasts_in_window(
        self, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """{seller_id, forecast_for, predicted_surplus_kwh, confidence} rows."""

    @abstractmethod
    async def get_recent_accuracy(self) -> list[dict[str, Any]]:
        """Scored forecasts: {seller_id, accuracy_delta_kwh} (non-null delta)."""


def aggregate_hourly(
    rows: list[dict[str, Any]],
    demand_signal,
) -> list[HourlyOutlook]:
    """Group forecast rows by target hour, sum surplus, build a confidence
    band, and subtract expected demand to get net position per hour."""
    by_hour: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_hour[str(r["forecast_for"])].append(r)

    hourly: list[HourlyOutlook] = []
    for forecast_for in sorted(by_hour):
        group = by_hour[forecast_for]
        surplus = round(sum(float(r["predicted_surplus_kwh"]) for r in group), 4)
        mean_conf = sum(float(r["confidence"]) for r in group) / len(group)
        # Wider band when confidence is low. band = (1 - conf) * surplus.
        half_band = round((1 - mean_conf) * surplus, 4)
        hour = datetime.fromisoformat(forecast_for.replace("Z", "+00:00")).hour
        demand = round(demand_signal.expected_demand_kwh(hour), 4)
        hourly.append(
            HourlyOutlook(
                forecast_for=forecast_for,
                predicted_surplus_kwh=surplus,
                lower_kwh=round(max(0.0, surplus - half_band), 4),
                upper_kwh=round(surplus + half_band, 4),
                expected_demand_kwh=demand,
                net_position_kwh=round(surplus - demand, 4),
            )
        )
    return hourly


def aggregate_per_seller(rows: list[dict[str, Any]]) -> list[SellerOutlook]:
    by_seller: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_seller[str(r["seller_id"])].append(r)
    out: list[SellerOutlook] = []
    for seller_id, group in by_seller.items():
        total = round(sum(float(r["predicted_surplus_kwh"]) for r in group), 4)
        mean_conf = round(sum(float(r["confidence"]) for r in group) / len(group), 4)
        out.append(SellerOutlook(seller_id=seller_id, total_predicted_kwh=total, mean_confidence=mean_conf))
    return sorted(out, key=lambda s: s.total_predicted_kwh, reverse=True)


def compute_drift_flags(accuracy_rows: list[dict[str, Any]]) -> list[DriftFlag]:
    """Flag sellers whose mean absolute accuracy delta exceeds the threshold
    over enough scored forecasts to be meaningful."""
    by_seller: dict[str, list[float]] = defaultdict(list)
    for r in accuracy_rows:
        delta = r.get("accuracy_delta_kwh")
        if delta is not None:
            by_seller[str(r["seller_id"])].append(abs(float(delta)))

    flags: list[DriftFlag] = []
    for seller_id, deltas in by_seller.items():
        if len(deltas) < MIN_SCORED_FOR_DRIFT:
            continue
        mean_abs = sum(deltas) / len(deltas)
        if mean_abs > ACCURACY_DRIFT_THRESHOLD_KWH:
            flags.append(
                DriftFlag(
                    seller_id=seller_id,
                    mean_abs_delta_kwh=round(mean_abs, 4),
                    scored_count=len(deltas),
                )
            )
    return sorted(flags, key=lambda f: f.mean_abs_delta_kwh, reverse=True)


def _fallback_summary(
    total_surplus: float, total_demand: float, net: float, seller_count: int, drift_count: int
) -> str:
    position = "surplus" if net >= 0 else "shortfall"
    parts = [
        f"Over the next {FLEET_HORIZON_HOURS}h, {seller_count} seller(s) are expected to "
        f"generate ~{total_surplus:.1f} kWh of surplus against ~{total_demand:.1f} kWh of "
        f"community demand — a net {position} of {abs(net):.1f} kWh."
    ]
    if net < 0:
        parts.append("The pool is likely short; importing may be needed at peak hours.")
    else:
        parts.append("The pool should cover demand, with headroom to export or store.")
    if drift_count:
        parts.append(f"{drift_count} seller(s) show forecast-accuracy drift — check their meters.")
    return " ".join(parts)


async def _outlook_summary(
    total_surplus: float, total_demand: float, net: float, seller_count: int, drift_count: int
) -> str:
    """Short NL outlook. Reuses the recommender's Groq-or-fallback approach:
    if GROQ_API_KEY is set, ask the model; otherwise deterministic template."""
    import logging

    logger = logging.getLogger(__name__)
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return _fallback_summary(total_surplus, total_demand, net, seller_count, drift_count)
    try:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=api_key)
        prompt = (
            f"You are a grid operator's assistant. In 2 short sentences, summarise the "
            f"next {FLEET_HORIZON_HOURS}h outlook for a community solar pool. "
            f"Expected surplus: {total_surplus:.1f} kWh across {seller_count} sellers. "
            f"Expected demand: {total_demand:.1f} kWh. Net position: {net:.1f} kWh "
            f"({'surplus' if net >= 0 else 'shortfall'}). "
            f"{drift_count} sellers show forecast-accuracy drift. "
            f"Be concrete and actionable; no preamble."
        )
        resp = await client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "mixtral-8x7b-32768"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:  # pragma: no cover - network path
        logger.warning("Groq outlook summary failed (%s), using fallback", e)
        return _fallback_summary(total_surplus, total_demand, net, seller_count, drift_count)


class SupabaseFleetStore(FleetStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_forecasts_in_window(self, start, end):
        result = (
            self._client.table("surplus_forecasts")
            .select("seller_id, forecast_for, predicted_surplus_kwh, confidence")
            .gte("forecast_for", start.isoformat())
            .lt("forecast_for", end.isoformat())
            .execute()
        )
        return result.data or []

    async def get_recent_accuracy(self):
        result = (
            self._client.table("surplus_forecasts")
            .select("seller_id, accuracy_delta_kwh")
            .not_.is_("accuracy_delta_kwh", "null")
            .execute()
        )
        return result.data or []


_store: FleetStore | None = None


def _get_store() -> FleetStore:
    global _store
    if _store is None:
        _store = SupabaseFleetStore()
    return _store


def set_store(store: FleetStore | None) -> None:
    global _store
    _store = store


async def get_fleet_outlook(now: datetime | None = None) -> FleetOutlook:
    """Build the full fleet outlook. Degrades gracefully to an empty outlook
    (net 0, no crash) when there are no forecasts yet."""
    now = now or datetime.now(timezone.utc)
    store = _get_store()
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=FLEET_HORIZON_HOURS + 1)

    rows = await store.get_forecasts_in_window(start, end)
    accuracy_rows = await store.get_recent_accuracy()

    hourly = aggregate_hourly(rows, get_demand_signal())
    per_seller = aggregate_per_seller(rows)
    drift_flags = compute_drift_flags(accuracy_rows)

    total_surplus = round(sum(h.predicted_surplus_kwh for h in hourly), 4)
    total_demand = round(sum(h.expected_demand_kwh for h in hourly), 4)
    net = round(total_surplus - total_demand, 4)

    summary = await _outlook_summary(
        total_surplus, total_demand, net, len(per_seller), len(drift_flags)
    )

    return FleetOutlook(
        horizon_hours=FLEET_HORIZON_HOURS,
        total_predicted_surplus_kwh=total_surplus,
        total_expected_demand_kwh=total_demand,
        net_position_kwh=net,
        hourly=hourly,
        per_seller=per_seller,
        drift_flags=drift_flags,
        summary=summary,
    )


async def get_net_position_kwh(now: datetime | None = None) -> float | None:
    """Lightweight net-position lookup for the recommendation feed-in.
    Returns None when there are no forecasts (so recommend() no-ops)."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=FLEET_HORIZON_HOURS + 1)
    rows = await _get_store().get_forecasts_in_window(start, end)
    if not rows:
        return None
    hourly = aggregate_hourly(rows, get_demand_signal())
    return round(sum(h.net_position_kwh for h in hourly), 4)
