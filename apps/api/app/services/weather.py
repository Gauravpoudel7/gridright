"""Pluggable weather provider for surplus forecasting (Phase 3).

Provider selection is env-driven, never a hardcoded vendor call:
- WEATHER_PROVIDER=mock  (default) → deterministic MockWeatherProvider
- WEATHER_PROVIDER=open-meteo      → Open-Meteo (no API key required;
  WEATHER_API_URL overrides the endpoint)

Lookups are cached per region (lat/lng rounded to REGION_DECIMALS) so two
sellers in the same area share one provider call per forecast run.
"""
from __future__ import annotations

import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# PLACEHOLDER region granularity: 1 decimal ≈ 11 km cells. Tune with real
# seller density later.
REGION_DECIMALS = 1


@dataclass
class HourlyWeather:
    """One forecast hour."""
    hour_offset: int          # hours from "now" (0 = current hour)
    cloud_cover_pct: float    # 0–100
    temperature_c: float


@dataclass
class WeatherForecast:
    latitude: float
    longitude: float
    hours: list[HourlyWeather] = field(default_factory=list)


def region_key(latitude: float, longitude: float) -> str:
    """Bucket coordinates into a region cell for cache sharing."""
    return f"{round(latitude, REGION_DECIMALS)}:{round(longitude, REGION_DECIMALS)}"


class WeatherProvider(ABC):
    @abstractmethod
    async def get_forecast(self, latitude: float, longitude: float, hours: int) -> WeatherForecast:
        ...


class MockWeatherProvider(WeatherProvider):
    """Deterministic synthetic weather: mild sinusoidal cloud cover keyed on
    the region, so tests get stable, region-dependent values with no network."""

    def __init__(self) -> None:
        self.call_count = 0

    async def get_forecast(self, latitude: float, longitude: float, hours: int) -> WeatherForecast:
        self.call_count += 1
        seed = abs(math.sin(round(latitude, REGION_DECIMALS) + round(longitude, REGION_DECIMALS)))
        forecast = WeatherForecast(latitude=latitude, longitude=longitude)
        for h in range(hours):
            cloud = 30 + 40 * abs(math.sin(seed + h / 6))  # 30–70%
            forecast.hours.append(
                HourlyWeather(hour_offset=h, cloud_cover_pct=round(cloud, 1), temperature_c=22.0)
            )
        return forecast


class OpenMeteoProvider(WeatherProvider):
    """Open-Meteo hourly forecast (free, keyless). Selected via env, never
    hardcoded as the only path."""

    def __init__(self) -> None:
        self.base_url = os.getenv("WEATHER_API_URL", "https://api.open-meteo.com/v1/forecast")

    async def get_forecast(self, latitude: float, longitude: float, hours: int) -> WeatherForecast:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                self.base_url,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "hourly": "cloud_cover,temperature_2m",
                    "forecast_hours": hours,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        clouds = data["hourly"]["cloud_cover"]
        temps = data["hourly"]["temperature_2m"]
        forecast = WeatherForecast(latitude=latitude, longitude=longitude)
        for h in range(min(hours, len(clouds))):
            forecast.hours.append(
                HourlyWeather(hour_offset=h, cloud_cover_pct=float(clouds[h]), temperature_c=float(temps[h]))
            )
        return forecast


class RegionCachedWeather:
    """Wraps a provider with a per-run region cache: one upstream call per
    region cell, shared by every seller in that cell."""

    def __init__(self, provider: WeatherProvider) -> None:
        self._provider = provider
        self._cache: dict[str, WeatherForecast] = {}

    async def get_forecast(self, latitude: float, longitude: float, hours: int) -> WeatherForecast:
        key = f"{region_key(latitude, longitude)}:{hours}"
        if key not in self._cache:
            self._cache[key] = await self._provider.get_forecast(latitude, longitude, hours)
        return self._cache[key]


_provider: WeatherProvider | None = None


def get_provider() -> WeatherProvider:
    global _provider
    if _provider is None:
        name = os.getenv("WEATHER_PROVIDER", "mock")
        _provider = OpenMeteoProvider() if name == "open-meteo" else MockWeatherProvider()
    return _provider


def set_provider(provider: WeatherProvider | None) -> None:
    global _provider
    _provider = provider
