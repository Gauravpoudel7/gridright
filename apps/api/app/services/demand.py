"""Pluggable demand / peak-hour signal (Phase 4, advanced roadmap).

Supply forecasts alone don't tell an operator whether the pool is long or
short — you need expected demand too. This is a deliberately simple,
swappable signal: a time-of-day heuristic to start, replaceable later with
a real demand model or a utility feed without touching callers.

Selected via env (DEMAND_SIGNAL), same convention as the weather provider.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

# PLACEHOLDER demand magnitudes (kWh per hour, community-wide) — illustrative
# time-of-day shape, tune against real consumption data later.
BASE_DEMAND_KWH = 8.0          # overnight community baseline
PEAK_DEMAND_KWH = 22.0         # morning/evening peak
MIDDAY_DEMAND_KWH = 14.0       # daytime plateau
MORNING_PEAK_HOURS = range(6, 9)    # 06:00–08:59
EVENING_PEAK_HOURS = range(18, 22)  # 18:00–21:59
DAYTIME_HOURS = range(9, 18)        # 09:00–17:59


class DemandSignal(ABC):
    @abstractmethod
    def expected_demand_kwh(self, hour_of_day: int) -> float:
        """Expected community demand (kWh) for a given hour of the day."""


class TimeOfDayDemand(DemandSignal):
    """Heuristic: peak in the morning and evening, plateau midday, low at
    night. A stand-in for a real demand model / peak-hour tariff feed."""

    def expected_demand_kwh(self, hour_of_day: int) -> float:
        h = hour_of_day % 24
        if h in MORNING_PEAK_HOURS or h in EVENING_PEAK_HOURS:
            return PEAK_DEMAND_KWH
        if h in DAYTIME_HOURS:
            return MIDDAY_DEMAND_KWH
        return BASE_DEMAND_KWH


_signal: DemandSignal | None = None


def get_signal() -> DemandSignal:
    global _signal
    if _signal is None:
        # Only "time-of-day" exists today; env hook is here so a real signal
        # can be dropped in without changing callers.
        _signal = TimeOfDayDemand()
    return _signal


def set_signal(signal: DemandSignal | None) -> None:
    global _signal
    _signal = signal
