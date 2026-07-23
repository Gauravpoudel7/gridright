import os
import logging
from dataclasses import dataclass, replace
from datetime import time

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# mixtral-8x7b-32768 was decommissioned by Groq; llama-3.3-70b-versatile was
# deprecated in the June 2026 wave. openai/gpt-oss-120b is Groq's current
# recommended general-purpose production model. Override with GROQ_MODEL.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


@dataclass
class PoolState:
    current_absorption_kwh: float
    absorption_limit_kwh: float
    current_consumption_kwh: float


# PLACEHOLDER fleet feed-in tuning. Decision (b) from the Phase 4 spec: the
# fleet net-position outlook is passed as an EXPLICIT optional input to
# recommend() and nudges price within a bounded range — it is never read from
# the forecast table deep inside this logic. When no fleet context is given
# (no forecasts yet), the nudge is a no-op, so existing behavior is unchanged.
FLEET_REFERENCE_KWH = 50.0          # net magnitude that maps to the full nudge
FLEET_MAX_PRICE_NUDGE_PCT = 10.0    # cap on how far fleet balance moves price


@dataclass
class FleetContext:
    """Aggregated supply-demand outlook fed in from the fleet view (Phase 4).
    net_position_kwh > 0 = expected surplus, < 0 = expected shortfall."""
    net_position_kwh: float


def _fleet_price_factor(fleet: "FleetContext | None") -> float:
    """Multiplier applied to the recommended price from the fleet outlook.

    Expected shortfall (net < 0) → scarcity → price up. Expected surplus
    (net > 0) → glut → price down. Bounded to ±FLEET_MAX_PRICE_NUDGE_PCT and
    a no-op (1.0) when no fleet context is supplied.
    """
    if fleet is None:
        return 1.0
    ratio = max(-1.0, min(1.0, -fleet.net_position_kwh / FLEET_REFERENCE_KWH))
    return 1.0 + ratio * (FLEET_MAX_PRICE_NUDGE_PCT / 100)


@dataclass
class RecommendationInput:
    seller_surplus_kwh: float
    time_of_day: time
    pool: PoolState
    # Optional fleet outlook (decision b). None → no fleet influence.
    fleet: "FleetContext | None" = None


@dataclass
class RecommendationResult:
    recommended_price: float
    recommended_absorption_kwh: float
    direction: str
    model_used: str


def rules_estimator(inp: RecommendationInput) -> RecommendationResult:
    feed_in_tariff = 0.10
    uplift = 0.15

    available_capacity = inp.pool.absorption_limit_kwh - inp.pool.current_absorption_kwh
    surplus = inp.seller_surplus_kwh

    total_contributed = inp.pool.current_absorption_kwh + surplus

    if inp.pool.current_consumption_kwh > total_contributed:
        direction = "import"
        recommended_absorption_kwh = round(surplus, 4)
        recommended_price = feed_in_tariff * (1 + uplift)
    elif surplus > available_capacity:
        direction = "export"
        recommended_absorption_kwh = round(available_capacity, 4)
        recommended_price = feed_in_tariff
    else:
        direction = "local_pool"
        recommended_absorption_kwh = round(min(surplus, available_capacity), 4)
        recommended_price = feed_in_tariff * (1 + uplift)

    # Fleet feed-in (decision b): nudge price by the expected supply-demand
    # balance. No-op when no fleet context was supplied.
    recommended_price = round(recommended_price * _fleet_price_factor(inp.fleet), 6)

    return RecommendationResult(
        recommended_price=recommended_price,
        recommended_absorption_kwh=recommended_absorption_kwh,
        direction=direction,
        model_used="rules",
    )


async def recommend(inp: RecommendationInput) -> RecommendationResult:
    if not GROQ_API_KEY:
        logger.info("GROQ_API_KEY not set, using rules fallback")
        return rules_estimator(inp)

    try:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=GROQ_API_KEY)
        # Anchor the model on the deterministic rules result (computed WITHOUT
        # the fleet nudge, which is applied once below). Giving the LLM this
        # baseline plus pool utilisation lets it refine within a sane range
        # instead of inventing a price from scratch — the failure mode that
        # made the LLM path no better (and riskier) than the rules alone.
        baseline = rules_estimator(replace(inp, fleet=None))
        limit = inp.pool.absorption_limit_kwh or 1.0
        utilization_pct = round(100 * inp.pool.current_absorption_kwh / limit, 1)
        fleet_note = (
            "no fleet outlook available"
            if inp.fleet is None
            else (
                f"fleet expects a net {'shortfall' if inp.fleet.net_position_kwh < 0 else 'surplus'} "
                f"of {abs(inp.fleet.net_position_kwh):.1f} kWh over the coming hours"
            )
        )
        prompt = (
            f"You price surplus solar for a community energy pool. "
            f"Seller surplus: {inp.seller_surplus_kwh} kWh at {inp.time_of_day.isoformat('minutes')}. "
            f"Pool absorbing {inp.pool.current_absorption_kwh} kWh of {inp.pool.absorption_limit_kwh} kWh "
            f"({utilization_pct}% utilised); community consuming {inp.pool.current_consumption_kwh} kWh. "
            f"Context: {fleet_note}. "
            f"A deterministic rules estimator suggests direction '{baseline.direction}', "
            f"base price ${baseline.recommended_price:.4f}/kWh, "
            f"absorb {baseline.recommended_absorption_kwh} kWh. "
            f"Use this as your anchor: pick the same direction unless clearly wrong, and keep the "
            f"price within roughly 20% of the anchor. Do NOT apply any grid scarcity adjustment "
            f"yourself — that is handled separately. Output the BASE price before any grid adjustment. "
            f"Direction is one of 'local_pool', 'import', or 'export'. "
            f"Respond with only a JSON object: "
            f'{{"direction": "<str>", "recommended_price": <float>, "recommended_absorption_kwh": <float>}}'
        )

        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        import json

        data = json.loads(response.choices[0].message.content)
        # Same fleet feed-in as the rules path — the single, deterministic grid
        # adjustment, applied once to the model's base price.
        price = float(data["recommended_price"]) * _fleet_price_factor(inp.fleet)
        return RecommendationResult(
            recommended_price=round(price, 6),
            recommended_absorption_kwh=round(float(data["recommended_absorption_kwh"]), 4),
            direction=str(data.get("direction", "local_pool")),
            model_used="groq",
        )
    except Exception as e:
        logger.warning("Groq API call failed (%s), falling back to rules", e)
        return rules_estimator(inp)
