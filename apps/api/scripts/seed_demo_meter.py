"""Seed demo meter readings for a seller through the REAL pipeline.

Nothing here bypasses the product: the script signs in as the seller,
registers a virtual meter via POST /sellers/me/meter-device, pushes readings
through the device-token-authenticated POST /meter-readings ingestion
endpoint (the same path a physical meter uses), then signs in as the
operator and calls POST /forecasts/run so the readings flow into
surplus_forecasts and the operator fleet view.

No hardcoded account IDs — the seller is addressed by email, the API resolves
identity from the JWT, and the device ID is derived per account. Re-running
replaces the seller's device (the API's register semantics), which cascades
away the old demo readings, so the script is idempotent.

Usage (defaults match supabase/seed.sql local test accounts):
    python scripts/seed_demo_meter.py
    python scripts/seed_demo_meter.py --seller-email someone@example.com --days 7

Env (defaults match local `supabase start` + local API):
    API_URL             default http://127.0.0.1:8000
    SUPABASE_URL        default http://127.0.0.1:54321
    SUPABASE_ANON_KEY   required (GoTrue apikey for password sign-in)
    SUPABASE_SERVICE_KEY  required only to set the seller's location if unset
                          (needed for forecasts; there is no user endpoint
                          for location yet)
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
# All app routes live under this prefix (see app/routers.py APIRouter prefix).
API_PREFIX = os.getenv("API_PREFIX", "/api/v1")
API_BASE = f"{API_URL.rstrip('/')}{API_PREFIX}"
SUPABASE_URL = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")


def sign_in(client: httpx.Client, email: str, password: str) -> str:
    """Password sign-in against GoTrue; returns the access token."""
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not anon_key:
        sys.exit("SUPABASE_ANON_KEY is required (anon/publishable key for sign-in)")
    resp = client.post(
        f"{SUPABASE_URL}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": anon_key},
        json={"email": email, "password": password},
    )
    if resp.status_code != 200:
        sys.exit(f"Sign-in failed for {email}: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def ensure_seller_location(seller_token: str, latitude: float, longitude: float) -> None:
    """Forecasting skips sellers without a location. There is no user-facing
    location endpoint yet, so set it via the service-role REST client — but
    only when it's currently null (never clobber a real value)."""
    service_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not service_key:
        print("  ! SUPABASE_SERVICE_KEY not set — skipping location check "
              "(forecasts require the seller to have latitude/longitude)")
        return
    # Resolve the seller's own id from their token — not from a hardcoded UUID.
    with httpx.Client(timeout=15) as client:
        me = client.get(
            f"{API_BASE}/me", headers={"Authorization": f"Bearer {seller_token}"}
        )
        me.raise_for_status()
        seller_id = me.json()["id"]

        headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
        }
        row = client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            params={"id": f"eq.{seller_id}", "select": "latitude,longitude"},
            headers=headers,
        )
        row.raise_for_status()
        data = row.json()
        if data and data[0]["latitude"] is not None:
            print(f"  seller already has a location: "
                  f"({data[0]['latitude']}, {data[0]['longitude']})")
            return
        patch = client.patch(
            f"{SUPABASE_URL}/rest/v1/profiles",
            params={"id": f"eq.{seller_id}"},
            headers=headers,
            json={"latitude": latitude, "longitude": longitude},
        )
        patch.raise_for_status()
        print(f"  set seller location to ({latitude}, {longitude})")


def solar_reading(rng: random.Random, at: datetime, peak_kw: float) -> dict:
    """One plausible hourly residential reading. Daylight bell curve for
    generation, base-plus-evening-peak consumption, most surplus exported."""
    h = at.hour
    if 6 <= h <= 18:
        # Bell over daylight hours, damped by that day's synthetic cloudiness.
        sun = math.sin(math.pi * (h - 6) / 12)
        day_factor = 0.6 + 0.4 * rng.random()  # per-day weather variation
        generation = round(peak_kw * sun * day_factor * (0.9 + 0.2 * rng.random()), 3)
    else:
        generation = 0.0
    base = 0.35 + 0.15 * rng.random()
    evening = 0.8 * math.exp(-((h - 19) ** 2) / 8)  # dinner-time bump
    consumption = round(base + evening + 0.2 * rng.random(), 3)
    surplus = max(0.0, generation - consumption)
    # Export most of the surplus, never more than was generated.
    grid_export = round(min(generation, surplus * (0.85 + 0.1 * rng.random())), 3)
    return {
        "reading_at": at.isoformat(),
        "generation_kwh": generation,
        "consumption_kwh": consumption,
        "grid_export_kwh": grid_export,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seller-email", default="seller@test.com")
    parser.add_argument("--seller-password", default="password123")
    parser.add_argument("--operator-email", default="operator@grid.com")
    parser.add_argument("--operator-password", default="password123")
    parser.add_argument("--days", type=int, default=14,
                        help="days of hourly history to generate (default 14, "
                             "matching the forecaster's HISTORY_DAYS)")
    parser.add_argument("--peak-kw", type=float, default=5.0,
                        help="array peak output per hour at full sun")
    parser.add_argument("--latitude", type=float, default=28.61)
    parser.add_argument("--longitude", type=float, default=77.21)
    args = parser.parse_args()

    # Deterministic per-account randomness: same account → same demo data.
    rng = random.Random(args.seller_email)
    device_id = "VM-" + hashlib.sha256(args.seller_email.encode()).hexdigest()[:12]

    with httpx.Client(timeout=30) as client:
        print(f"Signing in as {args.seller_email} ...")
        seller_token = sign_in(client, args.seller_email, args.seller_password)

        print(f"Registering virtual meter {device_id} ...")
        reg = client.post(
            f"{API_BASE}/sellers/me/meter-device",
            headers={"Authorization": f"Bearer {seller_token}"},
            json={"meter_device_id": device_id},
        )
        if reg.status_code != 201:
            sys.exit(f"Device registration failed: {reg.status_code} {reg.text}")
        device_token = reg.json()["device_token"]

        print("Ensuring seller has a location (needed for forecasts) ...")
        ensure_seller_location(seller_token, args.latitude, args.longitude)

        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(days=args.days)
        total = args.days * 24
        print(f"Ingesting {total} hourly readings via POST /meter-readings ...")
        accepted = 0
        at = start
        while at <= now:
            payload = solar_reading(rng, at, args.peak_kw)
            resp = client.post(
                f"{API_BASE}/meter-readings",
                headers={"Authorization": f"Bearer {device_token}"},
                json={"meter_device_id": device_id, **payload},
            )
            if resp.status_code != 201:
                sys.exit(f"Ingestion failed at {at}: {resp.status_code} {resp.text}")
            accepted += 1
            at += timedelta(hours=1)
        print(f"  {accepted} readings accepted")

        print(f"Signing in as {args.operator_email} to run the forecast job ...")
        operator_token = sign_in(client, args.operator_email, args.operator_password)
        run = client.post(
            f"{API_BASE}/forecasts/run",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        if run.status_code != 200:
            sys.exit(f"Forecast run failed: {run.status_code} {run.text}")
        print(f"  forecast job: {run.json()}")

        fleet = client.get(
            f"{API_BASE}/operator/fleet",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        if fleet.status_code == 200:
            data = fleet.json()
            print("Operator fleet outlook now shows:")
            print(f"  sellers in outlook: {len(data.get('per_seller', []))}")
            print(f"  total predicted surplus: "
                  f"{data.get('total_predicted_surplus_kwh')} kWh")
            print(f"  net position: {data.get('net_position_kwh')} kWh")
        else:
            print(f"  ! fleet check failed: {fleet.status_code} {fleet.text}")

    print("Done. The seller dashboard (readings + forecasts) and the operator "
          "fleet view are both fed from this data through the normal pipeline.")


if __name__ == "__main__":
    main()
