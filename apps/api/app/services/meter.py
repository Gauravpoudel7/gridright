"""Smart-meter ingestion service (Phase 2, advanced roadmap).

Real per-seller readings from a registered smart meter device. Devices
authenticate with a bearer token whose SHA-256 hash is stored in
meter_devices — the ingestion path never uses a user session.

Follows the repo's store-ABC pattern (see seller_dashboard / badge_service):
a swappable store so tests run against an in-memory dict, production against
Supabase via the service-role client.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from abc import ABC, abstractmethod
from typing import Any

# PLACEHOLDER sanity bounds for one reading interval — tune to real meter
# hardware later. A residential rooftop array won't exceed this per reading.
MAX_KWH_PER_READING = 100.0


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_device_token() -> str:
    """Random device token, shown to the seller once at registration."""
    return f"gr_meter_{secrets.token_urlsafe(24)}"


class MeterValidationError(Exception):
    """Payload failed a bounds/semantic check (HTTP 422)."""


class MeterAuthError(Exception):
    """Unknown device or wrong token (HTTP 401)."""


def validate_reading(
    generation_kwh: float, consumption_kwh: float, grid_export_kwh: float
) -> None:
    """Bounds checks beyond basic type validation. Mirrors the DB constraints
    so bad payloads fail fast with a clear message instead of a DB error."""
    for name, value in (
        ("generation_kwh", generation_kwh),
        ("consumption_kwh", consumption_kwh),
        ("grid_export_kwh", grid_export_kwh),
    ):
        if value < 0:
            raise MeterValidationError(f"{name} must be >= 0")
        if value > MAX_KWH_PER_READING:
            raise MeterValidationError(
                f"{name} exceeds the per-reading bound of {MAX_KWH_PER_READING} kWh"
            )
    if grid_export_kwh > generation_kwh:
        raise MeterValidationError("grid_export_kwh cannot exceed generation_kwh")


class MeterStore(ABC):
    @abstractmethod
    async def get_device(self, meter_device_id: str) -> dict[str, Any] | None:
        """Return {seller_id, meter_device_id, device_token_hash} or None."""

    @abstractmethod
    async def get_device_for_seller(self, seller_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def register_device(
        self, seller_id: str, meter_device_id: str, device_token_hash: str
    ) -> dict[str, Any]:
        """Insert (or replace the seller's existing) device row."""

    @abstractmethod
    async def insert_reading(self, reading: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_recent_readings(self, seller_id: str, limit: int) -> list[dict[str, Any]]:
        """Newest-first readings for the seller."""


class SupabaseMeterStore(MeterStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def get_device(self, meter_device_id: str) -> dict[str, Any] | None:
        result = (
            self._client.table("meter_devices")
            .select("seller_id, meter_device_id, device_token_hash")
            .eq("meter_device_id", meter_device_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def get_device_for_seller(self, seller_id: str) -> dict[str, Any] | None:
        result = (
            self._client.table("meter_devices")
            .select("seller_id, meter_device_id, created_at")
            .eq("seller_id", seller_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def register_device(
        self, seller_id: str, meter_device_id: str, device_token_hash: str
    ) -> dict[str, Any]:
        # One device per seller (DB unique constraint) — re-registering
        # replaces the previous device and invalidates its token.
        self._client.table("meter_devices").delete().eq("seller_id", seller_id).execute()
        result = (
            self._client.table("meter_devices")
            .insert(
                {
                    "seller_id": seller_id,
                    "meter_device_id": meter_device_id,
                    "device_token_hash": device_token_hash,
                }
            )
            .execute()
        )
        return result.data[0]

    async def insert_reading(self, reading: dict[str, Any]) -> dict[str, Any]:
        result = self._client.table("meter_readings").insert(reading).execute()
        return result.data[0]

    async def get_recent_readings(self, seller_id: str, limit: int) -> list[dict[str, Any]]:
        result = (
            self._client.table("meter_readings")
            .select(
                "reading_at, generation_kwh, consumption_kwh, surplus_kwh, grid_export_kwh"
            )
            .eq("seller_id", seller_id)
            .order("reading_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []


_store: MeterStore | None = None


def _get_store() -> MeterStore:
    global _store
    if _store is None:
        _store = SupabaseMeterStore()
    return _store


def set_store(store: MeterStore | None) -> None:
    global _store
    _store = store


async def ingest_reading(
    meter_device_id: str,
    device_token: str,
    reading_at: str,
    generation_kwh: float,
    consumption_kwh: float,
    grid_export_kwh: float,
) -> dict[str, Any]:
    """Authenticate the device, validate the payload, store the reading.

    Raises MeterAuthError for unknown device / bad token, MeterValidationError
    for out-of-bounds values. Note: surplus_kwh is computed by the DB
    (generated column), never accepted from the device.
    """
    device = await _get_store().get_device(meter_device_id)
    # Same error for unknown device and bad token — don't leak which one.
    if device is None or not secrets.compare_digest(
        device["device_token_hash"], hash_device_token(device_token)
    ):
        raise MeterAuthError("Unknown device or invalid device token")

    validate_reading(generation_kwh, consumption_kwh, grid_export_kwh)

    return await _get_store().insert_reading(
        {
            "seller_id": device["seller_id"],
            "meter_device_id": meter_device_id,
            "reading_at": reading_at,
            "generation_kwh": generation_kwh,
            "consumption_kwh": consumption_kwh,
            "grid_export_kwh": grid_export_kwh,
        }
    )


async def register_device(seller_id: str, meter_device_id: str) -> dict[str, Any]:
    """Register (or replace) the seller's meter device.

    Returns the row plus the plaintext token — the only time it's visible.
    """
    token = generate_device_token()
    row = await _get_store().register_device(
        seller_id, meter_device_id, hash_device_token(token)
    )
    return {**row, "device_token": token}


async def get_device_for_seller(seller_id: str) -> dict[str, Any] | None:
    return await _get_store().get_device_for_seller(seller_id)


async def get_recent_readings(seller_id: str, limit: int = 48) -> list[dict[str, Any]]:
    return await _get_store().get_recent_readings(seller_id, limit)
