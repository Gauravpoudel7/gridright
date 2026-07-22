#!/usr/bin/env python3
"""GridRight virtual smart meter simulator.

Pushes small dummy solar readings to the GridRight API on a fixed interval.
Completely standalone — no GridRight code imported.

Usage
-----
1. In the seller dashboard, enter pairing code:  VSIM-001
   (or any code that doesn't start with EXPIRED/CLAIMED/BADCODE)
   The dashboard will show a one-time device token — copy it.

2. Run this script:
       python sim.py --token gr_meter_<your_token> --meter-id METER-VSIM-001

   Or set env vars and run without flags:
       GRIDRIGHT_DEVICE_TOKEN=gr_meter_... GRIDRIGHT_METER_ID=METER-VSIM-001 python sim.py

Options
-------
  --token      Device token shown once after binding (or GRIDRIGHT_DEVICE_TOKEN)
  --meter-id   Meter ID shown in the dashboard (or GRIDRIGHT_METER_ID)
  --api        API base URL (default: https://gridright-api.onrender.com)
  --interval   Seconds between readings (default: 60)
  --once       Push a single reading and exit
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
import urllib.request
import urllib.error
import json
from datetime import datetime, timezone


API_DEFAULT = "https://gridright-api.onrender.com"

# Keep generation tiny so the operator's devnet SOL lasts.
# A real residential panel might do 3-5 kWh/h; we simulate ~0.05-0.4 kWh
# per reading so a full day of readings totals < 10 kWh.
GEN_BASE_KWH   = 0.15   # average generation per reading
CONS_BASE_KWH  = 0.06   # average consumption per reading


def _solar_factor(t: datetime) -> float:
    """Simple day/night curve: peaks at noon, zero at night."""
    hour = t.hour + t.minute / 60.0
    if hour < 6 or hour > 20:
        return 0.0
    angle = math.pi * (hour - 6) / 14.0
    return max(0.0, math.sin(angle))


def make_reading(meter_id: str) -> dict:
    now = datetime.now(timezone.utc)
    factor = _solar_factor(now)
    noise = lambda: random.uniform(0.85, 1.15)

    generation   = round(GEN_BASE_KWH  * factor * noise(), 4)
    consumption  = round(CONS_BASE_KWH * noise(), 4)
    # grid_export is what actually goes to the pool (surplus after self-use)
    grid_export  = round(max(0.0, generation - consumption) * random.uniform(0.7, 0.95), 4)

    return {
        "meter_device_id": meter_id,
        "reading_at": now.isoformat(),
        "generation_kwh": generation,
        "consumption_kwh": consumption,
        "grid_export_kwh": grid_export,
    }


def push(api: str, token: str, reading: dict) -> tuple[int, str]:
    body = json.dumps(reading).encode()
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/v1/meter-readings",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as exc:
        return 0, str(exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="GridRight virtual meter sim")
    parser.add_argument("--token",    default=os.getenv("GRIDRIGHT_DEVICE_TOKEN", ""))
    parser.add_argument("--meter-id", default=os.getenv("GRIDRIGHT_METER_ID", "METER-VSIM-001"))
    parser.add_argument("--api",      default=os.getenv("GRIDRIGHT_API_URL", API_DEFAULT))
    parser.add_argument("--interval", type=int, default=60, help="seconds between readings")
    parser.add_argument("--once",     action="store_true", help="push one reading and exit")
    args = parser.parse_args()

    if not args.token:
        print("ERROR: provide --token or set GRIDRIGHT_DEVICE_TOKEN", file=sys.stderr)
        print("  Bind the meter in the seller dashboard (pairing code: VSIM-001),", file=sys.stderr)
        print("  copy the one-time device token, then re-run with --token <token>", file=sys.stderr)
        sys.exit(1)

    print(f"Virtual meter  : {args.meter_id}")
    print(f"API            : {args.api}")
    print(f"Interval       : {args.interval}s")
    print(f"Token          : {args.token[:16]}…")
    print()

    while True:
        reading = make_reading(args.meter_id)
        status, body = push(args.api, args.token, reading)
        ts = datetime.now().strftime("%H:%M:%S")
        if status == 201:
            print(f"[{ts}] ✓  gen={reading['generation_kwh']:.4f} kWh  "
                  f"cons={reading['consumption_kwh']:.4f} kWh  "
                  f"export={reading['grid_export_kwh']:.4f} kWh")
        else:
            print(f"[{ts}] ✗  HTTP {status}: {body[:120]}")

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
