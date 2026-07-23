"""LearnedDemand: a real demand curve learned from meter consumption history.

Covers: the two-step community profile (sum per clock hour, then average by
hour-of-day), the per-hour cold-start fallback to the heuristic when history is
thin, refresh() TTL caching, and graceful degradation when the store errors.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import demand
from app.services.demand import (
    DemandStore,
    LearnedDemand,
    MIN_SAMPLES_PER_HOUR,
    TimeOfDayDemand,
    build_demand_profile,
    get_signal,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


class DictDemandStore(DemandStore):
    def __init__(self, readings=None, fail=False):
        self.readings = readings or []
        self.fail = fail
        self.calls = 0

    async def get_consumption_readings_since(self, since):
        self.calls += 1
        if self.fail:
            raise RuntimeError("store down")
        return [
            r
            for r in self.readings
            if datetime.fromisoformat(r["reading_at"]) >= since
        ]


def _readings_for_hour(hour, days, per_day_totals):
    """days readings at `hour`, one per day, each split across two sellers so
    the community total per clock hour is the given value."""
    rows = []
    for d in range(1, days + 1):
        at = (NOW - timedelta(days=d)).replace(hour=hour, minute=0)
        rows.append({"reading_at": at.isoformat(), "consumption_kwh": per_day_totals / 2})
        rows.append({"reading_at": at.isoformat(), "consumption_kwh": per_day_totals / 2})
    return rows


def test_build_profile_sums_community_then_averages_by_hour():
    # Hour 19: 4 days at community total 10 kWh → learned 10.0
    # Hour 20: only 2 days (< MIN_SAMPLES_PER_HOUR) → omitted, caller falls back
    readings = _readings_for_hour(19, days=4, per_day_totals=10.0)
    readings += _readings_for_hour(20, days=MIN_SAMPLES_PER_HOUR - 1, per_day_totals=99.0)
    profile = build_demand_profile(readings)
    assert profile[19] == pytest.approx(10.0)
    assert 20 not in profile


@pytest.mark.asyncio
async def test_learned_demand_uses_data_then_falls_back_per_hour():
    store = DictDemandStore(_readings_for_hour(19, days=5, per_day_totals=17.0))
    signal = LearnedDemand(store=store)
    await signal.refresh(now=NOW)

    # Hour 19 has enough history → learned value (not the heuristic's 22.0).
    assert signal.expected_demand_kwh(19) == pytest.approx(17.0)
    # Hour 3 has no history → identical to the heuristic (8.0 overnight).
    assert signal.expected_demand_kwh(3) == TimeOfDayDemand().expected_demand_kwh(3)


@pytest.mark.asyncio
async def test_refresh_is_cached_within_ttl():
    store = DictDemandStore(_readings_for_hour(19, days=5, per_day_totals=10.0))
    signal = LearnedDemand(store=store, ttl_seconds=900)
    await signal.refresh(now=NOW)
    await signal.refresh(now=NOW + timedelta(minutes=5))  # within TTL → no reload
    assert store.calls == 1
    await signal.refresh(now=NOW + timedelta(minutes=20))  # past TTL → reload
    assert store.calls == 2


@pytest.mark.asyncio
async def test_refresh_failure_degrades_to_heuristic_without_raising():
    signal = LearnedDemand(store=DictDemandStore(fail=True))
    await signal.refresh(now=NOW)  # must not raise
    # No learned hours → behaves exactly like the heuristic everywhere.
    heuristic = TimeOfDayDemand()
    for h in (3, 7, 12, 19):
        assert signal.expected_demand_kwh(h) == heuristic.expected_demand_kwh(h)


def test_env_selects_signal(monkeypatch):
    demand.set_signal(None)
    monkeypatch.setenv("DEMAND_SIGNAL", "learned")
    assert isinstance(get_signal(), LearnedDemand)
    demand.set_signal(None)
    monkeypatch.setenv("DEMAND_SIGNAL", "time-of-day")
    assert isinstance(get_signal(), TimeOfDayDemand)
    demand.set_signal(None)
    monkeypatch.delenv("DEMAND_SIGNAL", raising=False)
    assert isinstance(get_signal(), TimeOfDayDemand)  # default unchanged
    demand.set_signal(None)
