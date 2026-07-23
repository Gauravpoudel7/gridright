"""AI surplus forecasting (Phase 3, advanced roadmap).

Combines region-cached weather with each seller's own meter_readings history
to produce an explainable predicted-surplus curve for the next 24–48h.
Every forecast stores *why* (factors), not just the number. Accuracy is
computed once real readings land for a forecasted period.

Deliberately a deterministic model (historical hourly average × cloud
attenuation), not an LLM call — forecasts must be cheap, explainable, and
reproducible. The AI recommendation layer stays where it is (recommender.py).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.weather import RegionCachedWeather, get_provider

# PLACEHOLDER model parameters — the starting point / cold-start defaults.
# Once a seller has scored forecast history these are refined per-seller by
# learn_seller_params() below (the accuracy loop, previously collected but
# never fed back).
FORECAST_HORIZON_HOURS = 24          # how far ahead each run predicts
HISTORY_DAYS = 14                    # how much meter history informs the hourly profile
CLOUD_ATTENUATION = 0.6              # default fraction of generation lost at 100% cloud
MIN_HISTORY_READINGS = 4             # below this, confidence bottoms out
BASE_CONFIDENCE = 0.8                # confidence with solid history, clear model
LOW_HISTORY_CONFIDENCE = 0.3

# Per-seller learning (closes the accuracy loop).
RECENT_FORECASTS_FOR_LEARNING = 200  # how many recent scored forecasts to learn from
MIN_SAMPLES_FOR_LEARNING = 5         # need this many scored points before overriding defaults
LEARNED_ATTENUATION_MIN = 0.2        # clamp learned cloud response to a sane range
LEARNED_ATTENUATION_MAX = 0.9
MIN_HISTORY_FOR_CLOUD_FIT = 0.5      # kWh — ignore near-zero baselines (division noise)
MIN_CLOUD_FOR_FIT = 10.0             # % — ignore near-clear samples (division noise)
BIAS_DAMPING = 0.5                   # apply only half the observed bias (avoid oscillation)


class ForecastStore(ABC):
    @abstractmethod
    async def get_sellers_with_location(self) -> list[dict[str, Any]]:
        """[{id, latitude, longitude}] for sellers who can be forecast."""

    @abstractmethod
    async def get_readings_since(self, seller_id: str, since: datetime) -> list[dict[str, Any]]:
        """Meter readings newest-first: {reading_at, surplus_kwh}."""

    @abstractmethod
    async def insert_forecasts(self, rows: list[dict[str, Any]]) -> None:
        ...

    @abstractmethod
    async def get_forecasts_awaiting_accuracy(self, before: datetime) -> list[dict[str, Any]]:
        """Forecasts with forecast_for < before and accuracy not yet computed."""

    @abstractmethod
    async def get_actual_surplus_for_hour(self, seller_id: str, hour_start: datetime) -> float | None:
        """Sum of surplus_kwh readings in [hour_start, hour_start+1h), or None if no readings."""

    @abstractmethod
    async def set_accuracy(
        self, forecast_id: str, actual_surplus_kwh: float, accuracy_delta_kwh: float
    ) -> None:
        ...

    @abstractmethod
    async def get_recent_forecasts(self, seller_id: str, limit: int) -> list[dict[str, Any]]:
        ...


class SupabaseForecastStore(ForecastStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_sellers_with_location(self) -> list[dict[str, Any]]:
        result = (
            self._client.table("profiles")
            .select("id, latitude, longitude")
            .eq("role", "seller")
            .not_.is_("latitude", "null")
            .not_.is_("longitude", "null")
            .execute()
        )
        return result.data or []

    async def get_readings_since(self, seller_id: str, since: datetime) -> list[dict[str, Any]]:
        result = (
            self._client.table("meter_readings")
            .select("reading_at, surplus_kwh")
            .eq("seller_id", seller_id)
            .gte("reading_at", since.isoformat())
            .order("reading_at", desc=True)
            .execute()
        )
        return result.data or []

    async def insert_forecasts(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            self._client.table("surplus_forecasts").insert(rows).execute()

    async def get_forecasts_awaiting_accuracy(self, before: datetime) -> list[dict[str, Any]]:
        result = (
            self._client.table("surplus_forecasts")
            .select("id, seller_id, forecast_for, predicted_surplus_kwh")
            .lt("forecast_for", before.isoformat())
            .is_("accuracy_computed_at", "null")
            .execute()
        )
        return result.data or []

    async def get_actual_surplus_for_hour(self, seller_id: str, hour_start: datetime) -> float | None:
        result = (
            self._client.table("meter_readings")
            .select("surplus_kwh")
            .eq("seller_id", seller_id)
            .gte("reading_at", hour_start.isoformat())
            .lt("reading_at", (hour_start + timedelta(hours=1)).isoformat())
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        return sum(float(r["surplus_kwh"]) for r in rows)

    async def set_accuracy(
        self, forecast_id: str, actual_surplus_kwh: float, accuracy_delta_kwh: float
    ) -> None:
        self._client.table("surplus_forecasts").update(
            {
                "actual_surplus_kwh": actual_surplus_kwh,
                "accuracy_delta_kwh": accuracy_delta_kwh,
                "accuracy_computed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", forecast_id).execute()

    async def get_recent_forecasts(self, seller_id: str, limit: int) -> list[dict[str, Any]]:
        result = (
            self._client.table("surplus_forecasts")
            .select(
                "forecast_for, predicted_surplus_kwh, confidence, factors,"
                " actual_surplus_kwh, accuracy_delta_kwh, generated_at"
            )
            .eq("seller_id", seller_id)
            .order("forecast_for", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []


_store: ForecastStore | None = None


def _get_store() -> ForecastStore:
    global _store
    if _store is None:
        _store = SupabaseForecastStore()
    return _store


def set_store(store: ForecastStore | None) -> None:
    global _store
    _store = store


def build_hourly_profile(readings: list[dict[str, Any]]) -> dict[int, float]:
    """Average historical surplus_kwh per hour-of-day from meter readings."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for r in readings:
        at = datetime.fromisoformat(str(r["reading_at"]).replace("Z", "+00:00"))
        buckets[at.hour].append(float(r["surplus_kwh"]))
    return {hour: sum(vals) / len(vals) for hour, vals in buckets.items()}


def predict_hour(
    historical_avg_kwh: float,
    cloud_cover_pct: float,
    attenuation_coeff: float = CLOUD_ATTENUATION,
    bias_correction_kwh: float = 0.0,
) -> tuple[float, dict[str, Any]]:
    """One forecast hour: historical average attenuated by cloud cover, then
    corrected for this seller's observed forecast bias.

    attenuation_coeff and bias_correction_kwh default to the cold-start values
    (0.6 and 0.0), so callers without learned history get the original model.
    Returns (predicted_kwh, factors). Factors always explain the row, now
    including the learned coefficients that produced it.
    """
    retained = 1 - attenuation_coeff * (cloud_cover_pct / 100)
    predicted = max(0.0, round(historical_avg_kwh * retained - bias_correction_kwh, 4))
    factors = {
        "historical_avg_kwh": round(historical_avg_kwh, 4),
        "cloud_cover_pct": cloud_cover_pct,
        "cloud_attenuation_coeff": round(attenuation_coeff, 4),
        "cloud_attenuation_applied": round(1 - retained, 4),
        "bias_correction_kwh": round(bias_correction_kwh, 4),
        "model": "hourly_avg_x_cloud",
    }
    return predicted, factors


def learn_seller_params(recent_forecasts: list[dict[str, Any]]) -> tuple[float, float]:
    """Learn (cloud_attenuation_coeff, bias_correction_kwh) for one seller from
    their own scored forecasts — the accuracy data the system already stores
    but never used.

    Cloud response: each scored forecast recorded historical_avg_kwh and
    cloud_cover_pct (in factors) and, once readings landed, the actual surplus.
    Since actual ≈ historical * (1 - k * cloud/100), we back out
    k = (1 - actual/historical) * 100/cloud per usable sample and average them.
    Bias: the mean signed accuracy_delta_kwh (predicted - actual); a persistent
    over-prediction is subtracted back off (damped, to avoid oscillation).

    Both fall back to the cold-start defaults until MIN_SAMPLES_FOR_LEARNING
    usable points exist, and the attenuation is clamped to a sane band.
    """
    ks: list[float] = []
    deltas: list[float] = []
    for f in recent_forecasts:
        delta = f.get("accuracy_delta_kwh")
        actual = f.get("actual_surplus_kwh")
        if delta is None or actual is None:
            continue  # only scored forecasts carry signal
        deltas.append(float(delta))
        factors = f.get("factors") or {}
        hist = float(factors.get("historical_avg_kwh", 0.0))
        cloud = float(factors.get("cloud_cover_pct", 0.0))
        if hist >= MIN_HISTORY_FOR_CLOUD_FIT and cloud >= MIN_CLOUD_FOR_FIT and actual >= 0:
            ks.append((1 - float(actual) / hist) * 100.0 / cloud)

    attenuation = CLOUD_ATTENUATION
    if len(ks) >= MIN_SAMPLES_FOR_LEARNING:
        attenuation = min(
            LEARNED_ATTENUATION_MAX, max(LEARNED_ATTENUATION_MIN, sum(ks) / len(ks))
        )

    bias = 0.0
    if len(deltas) >= MIN_SAMPLES_FOR_LEARNING:
        bias = round(BIAS_DAMPING * (sum(deltas) / len(deltas)), 4)

    return attenuation, bias


async def run_forecast_job(now: datetime | None = None) -> dict[str, int]:
    """Generate FORECAST_HORIZON_HOURS of per-seller surplus forecasts.

    Weather is fetched through a per-run region cache, so sellers in the same
    region cell share one provider call.
    """
    now = now or datetime.now(timezone.utc)
    store = _get_store()
    weather = RegionCachedWeather(get_provider())

    sellers = await store.get_sellers_with_location()
    rows: list[dict[str, Any]] = []

    for seller in sellers:
        readings = await store.get_readings_since(
            seller["id"], now - timedelta(days=HISTORY_DAYS)
        )
        profile = build_hourly_profile(readings)
        confidence = (
            BASE_CONFIDENCE if len(readings) >= MIN_HISTORY_READINGS else LOW_HISTORY_CONFIDENCE
        )

        # Close the accuracy loop: refine cloud response + bias from this
        # seller's own scored history. Defaults (0.6, 0.0) until enough exists.
        recent = await store.get_recent_forecasts(
            seller["id"], RECENT_FORECASTS_FOR_LEARNING
        )
        attenuation_coeff, bias = learn_seller_params(recent)

        forecast = await weather.get_forecast(
            float(seller["latitude"]), float(seller["longitude"]), FORECAST_HORIZON_HOURS
        )

        start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        for hw in forecast.hours:
            target = start + timedelta(hours=hw.hour_offset)
            historical_avg = profile.get(target.hour, 0.0)
            predicted, factors = predict_hour(
                historical_avg, hw.cloud_cover_pct, attenuation_coeff, bias
            )
            factors["history_readings_used"] = len(readings)
            rows.append(
                {
                    "seller_id": seller["id"],
                    "forecast_for": target.isoformat(),
                    "predicted_surplus_kwh": predicted,
                    "confidence": confidence,
                    "factors": factors,
                }
            )

    await store.insert_forecasts(rows)
    return {"sellers": len(sellers), "forecasts": len(rows)}


async def compute_accuracy(now: datetime | None = None) -> dict[str, int]:
    """Fill predicted-vs-actual deltas for past forecasts that have readings.

    Forecasts whose hour has passed but has no readings yet are left for the
    next run (accuracy_computed_at stays null) — never scored against zero.
    """
    now = now or datetime.now(timezone.utc)
    store = _get_store()
    pending = await store.get_forecasts_awaiting_accuracy(before=now)

    computed = 0
    for fc in pending:
        hour_start = datetime.fromisoformat(str(fc["forecast_for"]).replace("Z", "+00:00"))
        actual = await store.get_actual_surplus_for_hour(fc["seller_id"], hour_start)
        if actual is None:
            continue
        delta = round(float(fc["predicted_surplus_kwh"]) - actual, 4)
        await store.set_accuracy(fc["id"], actual, delta)
        computed += 1

    return {"pending": len(pending), "computed": computed}


async def get_recent_forecasts(seller_id: str, limit: int = 48) -> list[dict[str, Any]]:
    return await _get_store().get_recent_forecasts(seller_id, limit)
