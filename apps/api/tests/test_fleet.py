"""Phase 4 (advanced roadmap): fleet outlook + recommendation feed-in tests.

Covers: aggregation over mock per-seller forecasts (sums, confidence band,
demand → net position), accuracy-drift flagging on a bad fixture, and the
recommend() fleet feed-in (decision b): output shifts with context present,
no error / unchanged behavior when absent.
"""
from datetime import datetime, time, timezone

import pytest

from app.services import demand, fleet
from app.services.demand import DemandSignal
from app.services.fleet import (
    ACCURACY_DRIFT_THRESHOLD_KWH,
    FleetStore,
    aggregate_hourly,
    aggregate_per_seller,
    compute_drift_flags,
    get_fleet_outlook,
    get_net_position_kwh,
)
from app.services.recommender import (
    FLEET_MAX_PRICE_NUDGE_PCT,
    FLEET_REFERENCE_KWH,
    FleetContext,
    PoolState,
    RecommendationInput,
    rules_estimator,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


class FlatDemand(DemandSignal):
    """Deterministic demand for tests: constant 10 kWh every hour."""

    def expected_demand_kwh(self, hour_of_day: int) -> float:
        return 10.0


class DictFleetStore(FleetStore):
    def __init__(self):
        self.forecasts: list[dict] = []
        self.accuracy: list[dict] = []

    async def get_forecasts_in_window(self, start, end):
        return [
            r for r in self.forecasts
            if start <= datetime.fromisoformat(r["forecast_for"]) < end
        ]

    async def get_recent_accuracy(self):
        return list(self.accuracy)


def forecast_row(seller, hour, kwh, conf):
    return {
        "seller_id": seller,
        "forecast_for": NOW.replace(hour=hour).isoformat(),
        "predicted_surplus_kwh": kwh,
        "confidence": conf,
    }


@pytest.fixture()
def fleet_store():
    store = DictFleetStore()
    fleet.set_store(store)
    demand.set_signal(FlatDemand())
    yield store
    fleet.set_store(None)
    demand.set_signal(None)


def test_hourly_aggregation_sums_and_bands():
    rows = [
        forecast_row("s-1", 13, 6.0, 0.8),
        forecast_row("s-2", 13, 4.0, 0.6),  # same hour → summed
        forecast_row("s-1", 14, 2.0, 0.8),
    ]
    hourly = aggregate_hourly(rows, FlatDemand())
    assert len(hourly) == 2

    h13 = hourly[0]
    assert h13.predicted_surplus_kwh == pytest.approx(10.0)
    # mean confidence 0.7 → half-band = 0.3 * 10 = 3
    assert h13.lower_kwh == pytest.approx(7.0)
    assert h13.upper_kwh == pytest.approx(13.0)
    assert h13.expected_demand_kwh == 10.0
    assert h13.net_position_kwh == pytest.approx(0.0)

    h14 = hourly[1]
    assert h14.predicted_surplus_kwh == pytest.approx(2.0)
    assert h14.net_position_kwh == pytest.approx(-8.0)  # shortfall hour


def test_per_seller_aggregation_averages_confidence():
    rows = [
        forecast_row("s-1", 13, 6.0, 0.8),
        forecast_row("s-1", 14, 2.0, 0.4),
        forecast_row("s-2", 13, 4.0, 0.6),
    ]
    per_seller = aggregate_per_seller(rows)
    assert [s.seller_id for s in per_seller] == ["s-2", "s-1"] or [s.seller_id for s in per_seller] == ["s-1", "s-2"]
    s1 = next(s for s in per_seller if s.seller_id == "s-1")
    assert s1.total_predicted_kwh == pytest.approx(8.0)
    assert s1.mean_confidence == pytest.approx(0.6)
    # sorted by predicted desc → s-1 (8.0) before s-2 (4.0)
    assert per_seller[0].seller_id == "s-1"


def test_drift_flags_on_bad_accuracy_fixture():
    rows = (
        # s-bad: mean |delta| = 2.0 > threshold, 3 scored → flagged
        [{"seller_id": "s-bad", "accuracy_delta_kwh": d} for d in (2.0, -2.5, 1.5)]
        # s-good: small deltas → not flagged
        + [{"seller_id": "s-good", "accuracy_delta_kwh": d} for d in (0.1, -0.2, 0.05)]
        # s-few: huge delta but only 1 scored → not enough evidence
        + [{"seller_id": "s-few", "accuracy_delta_kwh": 9.9}]
    )
    flags = compute_drift_flags(rows)
    assert [f.seller_id for f in flags] == ["s-bad"]
    assert flags[0].mean_abs_delta_kwh == pytest.approx(2.0)
    assert flags[0].scored_count == 3
    assert flags[0].mean_abs_delta_kwh > ACCURACY_DRIFT_THRESHOLD_KWH


@pytest.mark.asyncio
async def test_fleet_outlook_end_to_end(fleet_store):
    fleet_store.forecasts = [
        forecast_row("s-1", 13, 6.0, 0.8),
        forecast_row("s-2", 13, 4.0, 0.6),
        forecast_row("s-1", 14, 2.0, 0.8),
    ]
    fleet_store.accuracy = [
        {"seller_id": "s-1", "accuracy_delta_kwh": d} for d in (3.0, 2.0, 2.5)
    ]
    outlook = await get_fleet_outlook(now=NOW)
    assert outlook.total_predicted_surplus_kwh == pytest.approx(12.0)
    assert outlook.total_expected_demand_kwh == pytest.approx(20.0)
    assert outlook.net_position_kwh == pytest.approx(-8.0)
    assert [f.seller_id for f in outlook.drift_flags] == ["s-1"]
    # NL summary present (deterministic fallback without GROQ_API_KEY)
    assert "shortfall" in outlook.summary


@pytest.mark.asyncio
async def test_fleet_outlook_empty_no_crash(fleet_store):
    outlook = await get_fleet_outlook(now=NOW)
    assert outlook.total_predicted_surplus_kwh == 0
    assert outlook.net_position_kwh == 0
    assert outlook.hourly == []
    assert outlook.drift_flags == []
    # net position for the recommender: None (→ no-op), not 0 or an error
    assert await get_net_position_kwh(now=NOW) is None


def _base_input(fleet_ctx=None):
    return RecommendationInput(
        seller_surplus_kwh=100,
        time_of_day=time(12, 0),
        pool=PoolState(
            current_absorption_kwh=100,
            absorption_limit_kwh=1000,
            current_consumption_kwh=50,
        ),
        fleet=fleet_ctx,
    )


def test_recommend_no_fleet_context_unchanged():
    """Decision (b) graceful degradation: no context → exactly the old price."""
    result = rules_estimator(_base_input(None))
    assert result.recommended_price == pytest.approx(0.115)  # tariff * 1.15


def test_recommend_shifts_with_fleet_context():
    baseline = rules_estimator(_base_input(None)).recommended_price

    # Expected shortfall → scarcity → price up (capped at max nudge)
    short = rules_estimator(
        _base_input(FleetContext(net_position_kwh=-FLEET_REFERENCE_KWH))
    ).recommended_price
    assert short == pytest.approx(baseline * (1 + FLEET_MAX_PRICE_NUDGE_PCT / 100))

    # Expected surplus → glut → price down
    glut = rules_estimator(
        _base_input(FleetContext(net_position_kwh=FLEET_REFERENCE_KWH))
    ).recommended_price
    assert glut == pytest.approx(baseline * (1 - FLEET_MAX_PRICE_NUDGE_PCT / 100))

    # Half-magnitude net → half nudge; beyond reference → clamped
    half = rules_estimator(
        _base_input(FleetContext(net_position_kwh=-FLEET_REFERENCE_KWH / 2))
    ).recommended_price
    assert half == pytest.approx(baseline * (1 + FLEET_MAX_PRICE_NUDGE_PCT / 200))
    extreme = rules_estimator(
        _base_input(FleetContext(net_position_kwh=-10 * FLEET_REFERENCE_KWH))
    ).recommended_price
    assert extreme == pytest.approx(short)  # clamped to the same cap
