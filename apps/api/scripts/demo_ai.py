"""Live demo of the new AI logic — no database required.

Runs the real service functions against in-memory data so you can SEE:
  1. LearnedDemand learning a demand curve from consumption history
     (vs the old hardcoded 8/14/22 heuristic).
  2. The forecast learning loop recovering a seller's true cloud response
     and bias from scored history.
  3. The enriched recommender prompt (rules anchor + fleet context).

Run:  cd apps/api && python scripts/demo_ai.py
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.services.demand import (
    DemandStore,
    LearnedDemand,
    TimeOfDayDemand,
)
from app.services.forecast import CLOUD_ATTENUATION, learn_seller_params, predict_hour

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
LINE = "-" * 66


class InMemoryDemandStore(DemandStore):
    def __init__(self, readings):
        self._readings = readings

    async def get_consumption_readings_since(self, since):
        return [r for r in self._readings if datetime.fromisoformat(r["reading_at"]) >= since]


def synthetic_consumption():
    """14 days of hourly readings with a pronounced EVENING peak — a shape the
    fixed heuristic doesn't have, so the learned curve is visibly its own."""
    shape = {**{h: 5.0 for h in range(0, 6)}, **{h: 12.0 for h in range(6, 9)},
             **{h: 7.0 for h in range(9, 17)}, **{h: 18.0 for h in range(17, 22)},
             22: 8.0, 23: 8.0}
    rows = []
    for d in range(1, 15):
        day = NOW - timedelta(days=d)
        for h in range(24):
            rows.append({"reading_at": day.replace(hour=h).isoformat(),
                         "consumption_kwh": shape[h]})
    return rows


async def demo_learned_demand():
    print(LINE); print("1. LearnedDemand — real demand curve from meter history"); print(LINE)
    learned = LearnedDemand(store=InMemoryDemandStore(synthetic_consumption()))
    await learned.refresh(now=NOW)
    heuristic = TimeOfDayDemand()
    print(f"{'hour':>4} | {'heuristic (old)':>16} | {'learned (new)':>14}")
    for h in (3, 7, 12, 19, 23):
        print(f"{h:>4} | {heuristic.expected_demand_kwh(h):>16.1f} | {learned.expected_demand_kwh(h):>14.1f}")
    print("  -> learned curve reflects the actual evening peak (hour 19 = 18 kWh),")
    print("    where the heuristic guessed a flat 22; hours w/o data fall back.\n")


def demo_forecast_learning():
    print(LINE); print("2. Forecast learning loop — recover cloud response + bias"); print(LINE)
    # Scored history: this seller's panels really lose ~40% at 100% cloud (not
    # the 0.6 default), and every forecast over-predicted by 0.6 kWh.
    rows = []
    for _ in range(8):
        actual = 4.0 * (1 - 0.4 * 50.0 / 100)          # true response 0.4 @ 50% cloud
        rows.append({
            "actual_surplus_kwh": actual,
            "accuracy_delta_kwh": round((actual + 0.6) - actual, 4),  # over-predicted by 0.6
            "factors": {"historical_avg_kwh": 4.0, "cloud_cover_pct": 50.0},
        })
    att, bias = learn_seller_params(rows)
    print(f"  cold-start defaults : attenuation={CLOUD_ATTENUATION}, bias=0.0")
    print(f"  learned from history: attenuation={att}, bias={bias}")
    cold, _ = predict_hour(4.0, 50.0)
    warm, factors = predict_hour(4.0, 50.0, att, bias)
    print(f"  forecast @ 4kWh hist, 50% cloud:  default={cold} kWh  ->  learned={warm} kWh")
    print(f"  stored factors (self-explaining): {factors}\n")


def demo_recommender_prompt():
    print(LINE); print("3. Enriched recommender — rules anchor + fleet context"); print(LINE)
    from dataclasses import replace
    from datetime import time
    from app.services.recommender import (
        FleetContext, PoolState, RecommendationInput, rules_estimator,
    )
    inp = RecommendationInput(
        seller_surplus_kwh=40.0, time_of_day=time(19, 0),
        pool=PoolState(current_absorption_kwh=6000, absorption_limit_kwh=10000,
                       current_consumption_kwh=200),
        fleet=FleetContext(net_position_kwh=-30.0),  # expected shortfall
    )
    baseline = rules_estimator(replace(inp, fleet=None))
    print(f"  rules baseline (anchor): direction={baseline.direction}, "
          f"price=${baseline.recommended_price:.4f}, absorb={baseline.recommended_absorption_kwh}")
    print("  -> the LLM now receives this anchor + '60% pool utilised' + 'fleet")
    print("    expects a net shortfall of 30 kWh', so it refines instead of")
    print("    re-deriving the number the rules already produced.")
    print("  -> the deterministic fleet nudge still applies once, on top.\n")


async def main():
    print()
    await demo_learned_demand()
    demo_forecast_learning()
    demo_recommender_prompt()
    print("All three run against the REAL service code — no DB, no network.")


if __name__ == "__main__":
    asyncio.run(main())
