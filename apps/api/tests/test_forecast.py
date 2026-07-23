"""Phase 3 (advanced roadmap): surplus forecasting tests.

Covers: bounded sane output from mock weather + mock meter history,
non-empty factors on every forecast, correct accuracy on a known
predicted/actual pair, no-score-against-missing-readings, and the region
cache preventing duplicate provider calls for same-area sellers.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import forecast, weather
from app.services.forecast import (
    CLOUD_ATTENUATION,
    ForecastStore,
    FORECAST_HORIZON_HOURS,
    build_hourly_profile,
    compute_accuracy,
    learn_seller_params,
    predict_hour,
    run_forecast_job,
)
from app.services.weather import MockWeatherProvider, RegionCachedWeather


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


class DictForecastStore(ForecastStore):
    def __init__(self):
        self.sellers: list[dict] = []
        self.readings: dict[str, list[dict]] = {}
        self.forecasts: list[dict] = []
        self.accuracy_updates: list[tuple] = []
        self._next_id = 1

    async def get_sellers_with_location(self):
        return list(self.sellers)

    async def get_readings_since(self, seller_id, since):
        return [
            r
            for r in self.readings.get(seller_id, [])
            if datetime.fromisoformat(r["reading_at"]) >= since
        ]

    async def insert_forecasts(self, rows):
        for row in rows:
            self.forecasts.append({**row, "id": f"fc-{self._next_id}"})
            self._next_id += 1

    async def get_forecasts_awaiting_accuracy(self, before):
        return [
            f
            for f in self.forecasts
            if datetime.fromisoformat(f["forecast_for"]) < before
            and "accuracy_computed_at" not in f
        ]

    async def get_actual_surplus_for_hour(self, seller_id, hour_start):
        vals = [
            float(r["surplus_kwh"])
            for r in self.readings.get(seller_id, [])
            if hour_start <= datetime.fromisoformat(r["reading_at"]) < hour_start + timedelta(hours=1)
        ]
        return sum(vals) if vals else None

    async def set_accuracy(self, forecast_id, actual_surplus_kwh, accuracy_delta_kwh):
        self.accuracy_updates.append((forecast_id, actual_surplus_kwh, accuracy_delta_kwh))
        for f in self.forecasts:
            if f["id"] == forecast_id:
                f["actual_surplus_kwh"] = actual_surplus_kwh
                f["accuracy_delta_kwh"] = accuracy_delta_kwh
                f["accuracy_computed_at"] = NOW.isoformat()

    async def get_recent_forecasts(self, seller_id, limit):
        rows = [f for f in self.forecasts if f["seller_id"] == seller_id]
        return sorted(rows, key=lambda f: f["forecast_for"], reverse=True)[:limit]


def seed_history(store, seller_id, days=7, daily_noon_surplus=3.0):
    """Give a seller a steady history: surplus at 10:00–14:00 each day."""
    rows = []
    for d in range(1, days + 1):
        day = NOW - timedelta(days=d)
        for hour in (10, 11, 12, 13, 14):
            rows.append(
                {
                    "reading_at": day.replace(hour=hour).isoformat(),
                    "surplus_kwh": daily_noon_surplus,
                }
            )
    store.readings[seller_id] = rows


@pytest.fixture()
def stores():
    store = DictForecastStore()
    provider = MockWeatherProvider()
    forecast.set_store(store)
    weather.set_provider(provider)
    yield store, provider
    forecast.set_store(None)
    weather.set_provider(None)


@pytest.mark.asyncio
async def test_forecast_job_bounded_and_sane(stores):
    store, _ = stores
    store.sellers = [{"id": "seller-1", "latitude": 12.9, "longitude": 77.6}]
    seed_history(store, "seller-1", daily_noon_surplus=3.0)

    result = await run_forecast_job(now=NOW)
    assert result == {"sellers": 1, "forecasts": FORECAST_HORIZON_HOURS}

    for fc in store.forecasts:
        # bounded: never negative, never above the un-attenuated historical avg
        assert 0 <= fc["predicted_surplus_kwh"] <= 3.0
        assert 0 <= fc["confidence"] <= 1
        # explainability is mandatory, not optional
        assert fc["factors"], "factors must be non-empty"
        assert "historical_avg_kwh" in fc["factors"]
        assert "cloud_cover_pct" in fc["factors"]

    # midday hours (with history) predict > 0; night hours (no history) predict 0
    midday = [f for f in store.forecasts if "T12:" in f["forecast_for"]]
    night = [f for f in store.forecasts if "T03:" in f["forecast_for"]]
    assert midday and midday[0]["predicted_surplus_kwh"] > 0
    assert night and night[0]["predicted_surplus_kwh"] == 0


@pytest.mark.asyncio
async def test_low_history_seller_gets_low_confidence(stores):
    store, _ = stores
    store.sellers = [{"id": "seller-new", "latitude": 12.9, "longitude": 77.6}]
    store.readings["seller-new"] = []  # no history at all

    await run_forecast_job(now=NOW)
    assert all(f["confidence"] == forecast.LOW_HISTORY_CONFIDENCE for f in store.forecasts)


def test_predict_hour_known_values():
    # 4.0 kWh historical, 50% cloud, attenuation 0.6 → 4.0 * (1 - 0.3) = 2.8
    predicted, factors = predict_hour(4.0, 50.0)
    assert predicted == pytest.approx(2.8)
    assert factors["cloud_attenuation_applied"] == pytest.approx(0.3)
    assert factors["model"] == "hourly_avg_x_cloud"


def test_build_hourly_profile_averages_by_hour():
    readings = [
        {"reading_at": "2026-07-18T12:00:00+00:00", "surplus_kwh": 2.0},
        {"reading_at": "2026-07-19T12:30:00+00:00", "surplus_kwh": 4.0},
        {"reading_at": "2026-07-19T03:00:00+00:00", "surplus_kwh": 0.0},
    ]
    profile = build_hourly_profile(readings)
    assert profile[12] == pytest.approx(3.0)
    assert profile[3] == 0.0


@pytest.mark.asyncio
async def test_accuracy_on_known_pair(stores):
    store, _ = stores
    hour = NOW - timedelta(hours=2)
    store.forecasts.append(
        {
            "id": "fc-known",
            "seller_id": "seller-1",
            "forecast_for": hour.isoformat(),
            "predicted_surplus_kwh": 2.5,
        }
    )
    # actuals in that hour: 1.0 + 0.9 = 1.9 → delta = 2.5 - 1.9 = 0.6
    store.readings["seller-1"] = [
        {"reading_at": (hour + timedelta(minutes=10)).isoformat(), "surplus_kwh": 1.0},
        {"reading_at": (hour + timedelta(minutes=40)).isoformat(), "surplus_kwh": 0.9},
    ]

    result = await compute_accuracy(now=NOW)
    assert result == {"pending": 1, "computed": 1}
    fc_id, actual, delta = store.accuracy_updates[0]
    assert fc_id == "fc-known"
    assert actual == pytest.approx(1.9)
    assert delta == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_accuracy_skips_hours_without_readings(stores):
    store, _ = stores
    store.forecasts.append(
        {
            "id": "fc-noreads",
            "seller_id": "seller-1",
            "forecast_for": (NOW - timedelta(hours=2)).isoformat(),
            "predicted_surplus_kwh": 2.5,
        }
    )
    result = await compute_accuracy(now=NOW)
    # pending but NOT computed — never scored against zero
    assert result == {"pending": 1, "computed": 0}
    assert store.accuracy_updates == []


def _scored(historical, cloud, actual, predicted):
    """A scored forecast row as get_recent_forecasts would return it."""
    return {
        "predicted_surplus_kwh": predicted,
        "actual_surplus_kwh": actual,
        "accuracy_delta_kwh": round(predicted - actual, 4),
        "factors": {"historical_avg_kwh": historical, "cloud_cover_pct": cloud},
    }


def test_learn_params_cold_start_returns_defaults():
    # No scored history → the original model (default attenuation, no bias).
    assert learn_seller_params([]) == (CLOUD_ATTENUATION, 0.0)
    # Fewer than MIN_SAMPLES_FOR_LEARNING usable points → still defaults.
    assert learn_seller_params([_scored(4.0, 50.0, 2.8, 2.8)]) == (CLOUD_ATTENUATION, 0.0)


def test_learn_params_recovers_attenuation_and_bias():
    # Build 6 samples where actual = historical*(1 - 0.4*cloud/100), i.e. this
    # seller's true cloud response is 0.4 (clearer panels than the 0.6 default),
    # and each forecast over-predicted by 0.6 kWh (a positive, correctable bias).
    rows = []
    for _ in range(6):
        actual = 4.0 * (1 - 0.4 * 50.0 / 100)     # 3.2
        predicted = actual + 0.6                   # delta = +0.6
        rows.append(_scored(4.0, 50.0, actual, predicted))
    attenuation, bias = learn_seller_params(rows)
    assert attenuation == pytest.approx(0.4, abs=1e-6)
    assert bias == pytest.approx(0.3)  # BIAS_DAMPING (0.5) * mean delta (0.6)


def test_learn_params_clamps_extreme_attenuation():
    # actual far below historical → implied k > 1, must clamp to the max band.
    rows = [_scored(4.0, 50.0, 0.1, 2.0) for _ in range(6)]
    attenuation, _ = learn_seller_params(rows)
    assert attenuation <= 0.9


def test_predict_hour_applies_learned_params():
    # historical 4.0, 50% cloud, learned attenuation 0.4, bias 0.3:
    # 4.0 * (1 - 0.4*0.5) - 0.3 = 4.0*0.8 - 0.3 = 2.9
    predicted, factors = predict_hour(4.0, 50.0, 0.4, 0.3)
    assert predicted == pytest.approx(2.9)
    assert factors["cloud_attenuation_coeff"] == pytest.approx(0.4)
    assert factors["bias_correction_kwh"] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_run_forecast_job_uses_learned_params(stores):
    store, _ = stores
    store.sellers = [{"id": "seller-1", "latitude": 12.9, "longitude": 77.6}]
    seed_history(store, "seller-1", daily_noon_surplus=4.0)
    # Pre-load scored history implying a 0.4 cloud response (not the 0.6 default).
    for i in range(6):
        store.forecasts.append(
            {
                "id": f"scored-{i}",
                "seller_id": "seller-1",
                "forecast_for": (NOW - timedelta(days=1, hours=i)).isoformat(),
                "accuracy_computed_at": NOW.isoformat(),
                **_scored(4.0, 50.0, 3.2, 3.2),
            }
        )

    await run_forecast_job(now=NOW)

    fresh = [f for f in store.forecasts if f["id"].startswith("fc-")]
    assert fresh, "run should have produced new forecasts"
    assert all(f["factors"]["cloud_attenuation_coeff"] == pytest.approx(0.4) for f in fresh)


@pytest.mark.asyncio
async def test_region_cache_shares_weather_calls(stores):
    store, provider = stores
    # Two sellers ~1km apart (same 0.1° cell), one far away (different cell).
    store.sellers = [
        {"id": "s-a", "latitude": 12.91, "longitude": 77.61},
        {"id": "s-b", "latitude": 12.92, "longitude": 77.62},
        {"id": "s-c", "latitude": 28.60, "longitude": 77.20},
    ]
    await run_forecast_job(now=NOW)
    # 3 sellers but only 2 distinct region cells → exactly 2 provider calls
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_cache_wrapper_direct():
    provider = MockWeatherProvider()
    cached = RegionCachedWeather(provider)
    await cached.get_forecast(12.91, 77.61, 24)
    await cached.get_forecast(12.94, 77.63, 24)  # same 0.1° cell
    assert provider.call_count == 1
    await cached.get_forecast(28.6, 77.2, 24)  # different cell
    assert provider.call_count == 2
