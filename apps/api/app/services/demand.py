"""Pluggable demand / peak-hour signal (Phase 4, advanced roadmap).

Supply forecasts alone don't tell an operator whether the pool is long or
short — you need expected demand too. Two implementations share one interface:

- TimeOfDayDemand: a fixed morning/evening-peak heuristic (the original
  stand-in, and the cold-start fallback).
- LearnedDemand: a real signal that learns the community's expected demand
  per hour-of-day from meter_readings.consumption_kwh — the consumption data
  the meters already record but nothing used before. Deliberately a plain
  statistical profile (not an LLM): a demand curve that moves money must be
  cheap, explainable, and reproducible. Per hour with too little history it
  falls back to the heuristic, so a fresh community behaves exactly as before.

Selected via env (DEMAND_SIGNAL=time-of-day | learned), same convention as
the weather provider. Callers never change: both expose expected_demand_kwh()
and an async refresh() (a no-op for the heuristic).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# PLACEHOLDER demand magnitudes (kWh per hour, community-wide) — illustrative
# time-of-day shape, and the fallback whenever learned history is thin.
BASE_DEMAND_KWH = 8.0          # overnight community baseline
PEAK_DEMAND_KWH = 22.0         # morning/evening peak
MIDDAY_DEMAND_KWH = 14.0       # daytime plateau
MORNING_PEAK_HOURS = range(6, 9)    # 06:00–08:59
EVENING_PEAK_HOURS = range(18, 22)  # 18:00–21:59
DAYTIME_HOURS = range(9, 18)        # 09:00–17:59

# LearnedDemand tuning.
DEMAND_HISTORY_DAYS = 14        # how much consumption history informs the profile
MIN_SAMPLES_PER_HOUR = 3        # distinct days needed before a learned hour is trusted
DEMAND_REFRESH_TTL_SECONDS = 900  # cache the learned profile for 15 min between reloads


class DemandSignal(ABC):
    @abstractmethod
    def expected_demand_kwh(self, hour_of_day: int) -> float:
        """Expected community demand (kWh) for a given hour of the day."""

    async def refresh(self, now: datetime | None = None) -> None:
        """Reload any data-backed state. No-op by default; overridden by
        signals that learn from history. Callers await this before reading."""
        return None


class TimeOfDayDemand(DemandSignal):
    """Heuristic: peak in the morning and evening, plateau midday, low at
    night. Stand-in for a real demand model, and LearnedDemand's fallback."""

    def expected_demand_kwh(self, hour_of_day: int) -> float:
        h = hour_of_day % 24
        if h in MORNING_PEAK_HOURS or h in EVENING_PEAK_HOURS:
            return PEAK_DEMAND_KWH
        if h in DAYTIME_HOURS:
            return MIDDAY_DEMAND_KWH
        return BASE_DEMAND_KWH


class DemandStore(ABC):
    @abstractmethod
    async def get_consumption_readings_since(
        self, since: datetime
    ) -> list[dict[str, Any]]:
        """Community-wide meter readings: [{reading_at, consumption_kwh}]."""


class SupabaseDemandStore(DemandStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_consumption_readings_since(self, since):
        # Order newest-first with an explicit cap: PostgREST silently truncates
        # at its max-rows default (1000), so without this a busy community's
        # profile would train on an arbitrary subset. Capped, newest-first
        # truncation degrades to "slightly less history" instead.
        result = (
            self._client.table("meter_readings")
            .select("reading_at, consumption_kwh")
            .gte("reading_at", since.isoformat())
            .order("reading_at", desc=True)
            .limit(10000)
            .execute()
        )
        return result.data or []


def build_demand_profile(readings: list[dict[str, Any]]) -> dict[int, float]:
    """Learn expected community demand per hour-of-day from raw meter readings.

    Two-step, so a big community and a small one are treated the same way:
      1. Sum consumption across all sellers within each concrete clock hour
         (e.g. 2026-07-20 19:00) → the community's total demand that hour.
      2. Average those hourly totals by hour-of-day (0–23).
    Hours seen on fewer than MIN_SAMPLES_PER_HOUR distinct days are omitted so
    the caller falls back to the heuristic for them rather than trusting noise.
    """
    by_instant: dict[tuple[Any, int], float] = defaultdict(float)
    for r in readings:
        at = datetime.fromisoformat(str(r["reading_at"]).replace("Z", "+00:00"))
        by_instant[(at.date(), at.hour)] += float(r.get("consumption_kwh") or 0.0)

    by_hour: dict[int, list[float]] = defaultdict(list)
    for (_day, hour), total in by_instant.items():
        by_hour[hour].append(total)

    return {
        hour: round(sum(totals) / len(totals), 4)
        for hour, totals in by_hour.items()
        if len(totals) >= MIN_SAMPLES_PER_HOUR
    }


class LearnedDemand(DemandSignal):
    """Data-backed demand curve learned from meter_readings.consumption_kwh.

    Falls back to TimeOfDayDemand for any hour without enough history, so a new
    community with no readings behaves identically to the old heuristic until
    real data accumulates. refresh() reloads the profile at most once per TTL.
    """

    def __init__(
        self,
        store: DemandStore | None = None,
        ttl_seconds: int = DEMAND_REFRESH_TTL_SECONDS,
    ) -> None:
        self._store = store
        self._fallback = TimeOfDayDemand()
        self._profile: dict[int, float] = {}
        self._loaded_at: datetime | None = None
        self._ttl = timedelta(seconds=ttl_seconds)

    async def refresh(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        if self._loaded_at is not None and now - self._loaded_at < self._ttl:
            return
        since = now - timedelta(days=DEMAND_HISTORY_DAYS)
        try:  # never let a demand-history read (or store init) break pricing
            store = self._store or _get_demand_store()
            readings = await store.get_consumption_readings_since(since)
        except Exception as e:
            logger.warning("LearnedDemand refresh failed (%s), keeping fallback", e)
            self._loaded_at = now  # avoid hammering a failing store every request
            return
        self._profile = build_demand_profile(readings)
        self._loaded_at = now
        logger.info("LearnedDemand loaded %d learned hour(s)", len(self._profile))

    def expected_demand_kwh(self, hour_of_day: int) -> float:
        h = hour_of_day % 24
        if h in self._profile:
            return self._profile[h]
        return self._fallback.expected_demand_kwh(h)


_signal: DemandSignal | None = None
_demand_store: DemandStore | None = None


def get_signal() -> DemandSignal:
    global _signal
    if _signal is None:
        name = os.getenv("DEMAND_SIGNAL", "time-of-day")
        _signal = LearnedDemand() if name == "learned" else TimeOfDayDemand()
    return _signal


def set_signal(signal: DemandSignal | None) -> None:
    global _signal
    _signal = signal


def _get_demand_store() -> DemandStore:
    global _demand_store
    if _demand_store is None:
        _demand_store = SupabaseDemandStore()
    return _demand_store


def set_demand_store(store: DemandStore | None) -> None:
    global _demand_store
    _demand_store = store
