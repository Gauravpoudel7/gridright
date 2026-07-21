// DEMO-ONLY — purely client-side, no DB, no API. Reimplements the
// recommend → policy-check pipeline from
// apps/api/app/services/recommender.py (rules_estimator) and
// apps/api/app/services/policy_checker.py (check) faithfully, so the
// live demo dashboard reflects the same in-band / out-of-band split
// the real operator dashboard would show. Keep these constants in sync
// with the Python side if they change there.

// PLACEHOLDER numbers (mirrored from the Python recommender rules path)
export const FEED_IN_TARIFF = 0.10;          // $/kWh reference tariff
export const SELLER_UPLIFT = 0.15;          // 15% over tariff when local_pool
export const POOL_ABSORPTION_LIMIT_KWH = 100; // placeholder pool cap
export const POOL_BASE_CONSUMPTION_KWH = 80;  // placeholder community consumption

// PLACEHOLDER policy band (mirrored from policy_checker.py defaults)
export const POLICY_BAND_PCT = 10;           // ±10% around the reference tariff
export const POLICY_POOL_CAPACITY_LIMIT_KWH = 100;
export const POLICY_SELLER_UPLIFT_PCT = 15;
export const POLICY_OPERATOR_MARGIN_PCT = 5;
export const POLICY_FEED_IN_REFERENCE = FEED_IN_TARIFF;

export type PoolState = {
  currentAbsorptionKwh: number;
  absorptionLimitKwh: number;
  currentConsumptionKwh: number;
};

export type FleetContext = { netPositionKwh: number } | null;

export type RecommendInput = {
  sellerSurplusKwh: number;
  /** ISO HH:MM, mirrored from the Python `time` field. */
  timeOfDay: string;
  pool: PoolState;
  fleet?: FleetContext;
};

export type RecommendResult = {
  recommendedPrice: number;
  recommendedAbsorptionKwh: number;
  /** "local_pool" | "import" | "export" — same vocabulary as the Python side. */
  direction: "local_pool" | "import" | "export";
  modelUsed: "rules" | "groq";
};

const FLEET_REFERENCE_KWH = 50.0;
const FLEET_MAX_PRICE_NUDGE_PCT = 10.0;

function fleetPriceFactor(fleet: FleetContext): number {
  if (!fleet) return 1.0;
  const ratio = Math.max(-1, Math.min(1, -fleet.netPositionKwh / FLEET_REFERENCE_KWH));
  return 1 + ratio * (FLEET_MAX_PRICE_NUDGE_PCT / 100);
}

function round(n: number, decimals: number): number {
  const m = 10 ** decimals;
  return Math.round(n * m) / m;
}

/** Faithful TS port of apps/api/app/services/recommender.py:rules_estimator.
 *  The /demo environment has no GROQ key, so we always use the rules path;
 *  this matches the production fallback. */
export function recommend(input: RecommendInput): RecommendResult {
  const { sellerSurplusKwh, pool, fleet = null } = input;
  const availableCapacity = pool.absorptionLimitKwh - pool.currentAbsorptionKwh;
  const surplus = sellerSurplusKwh;
  const totalContributed = pool.currentAbsorptionKwh + surplus;

  let direction: "local_pool" | "import" | "export";
  let recommendedAbsorptionKwh: number;
  let recommendedPrice: number;

  if (pool.currentConsumptionKwh > totalContributed) {
    direction = "import";
    recommendedAbsorptionKwh = round(surplus, 4);
    recommendedPrice = FEED_IN_TARIFF * (1 + SELLER_UPLIFT);
  } else if (surplus > availableCapacity) {
    direction = "export";
    recommendedAbsorptionKwh = round(availableCapacity, 4);
    recommendedPrice = FEED_IN_TARIFF;
  } else {
    direction = "local_pool";
    recommendedAbsorptionKwh = round(Math.min(surplus, availableCapacity), 4);
    recommendedPrice = FEED_IN_TARIFF * (1 + SELLER_UPLIFT);
  }

  recommendedPrice = round(recommendedPrice * fleetPriceFactor(fleet), 6);
  return {
    recommendedPrice,
    recommendedAbsorptionKwh,
    direction,
    modelUsed: "rules",
  };
}

export type PolicyConfig = {
  bandWidthPercentage: number;
  poolCapacityLimitKwh: number;
};

export type PriceRecommendation = {
  recommendedPrice: number;
  recommendedAbsorptionKwh: number;
  direction: "local_pool" | "import" | "export";
};

export type PolicyCheckResult = {
  decision: "auto-approved" | "needs_review";
  deviationReason: string | null;
};

/** Faithful TS port of apps/api/app/services/policy_checker.py:check. */
export function checkPolicy(
  rec: PriceRecommendation,
  policy: PolicyConfig,
): PolicyCheckResult {
  const band = policy.bandWidthPercentage / 100;
  const tariff = FEED_IN_TARIFF;
  const lowerBound = tariff * (1 - band);
  const upperBound = tariff * (1 + band);

  const { recommendedPrice: price, recommendedAbsorptionKwh: absorption } = rec;

  if (price < lowerBound || price > upperBound) {
    if (price < lowerBound) {
      const deviationPct = round(((lowerBound - price) / tariff) * 100, 2);
      return {
        decision: "needs_review",
        deviationReason:
          `Recommended price $${price.toFixed(4)}/kWh is ${deviationPct}% below ` +
          `the reference tariff $${tariff.toFixed(4)}/kWh; ` +
          `band allows ±${policy.bandWidthPercentage}% ` +
          `(lower bound $${lowerBound.toFixed(4)}/kWh)`,
      };
    }
    const deviationPct = round(((price - upperBound) / tariff) * 100, 2);
    return {
      decision: "needs_review",
      deviationReason:
        `Recommended price $${price.toFixed(4)}/kWh is ${deviationPct}% above ` +
        `the reference tariff $${tariff.toFixed(4)}/kWh; ` +
        `band allows ±${policy.bandWidthPercentage}% ` +
        `(upper bound $${upperBound.toFixed(4)}/kWh)`,
    };
  }

  if (absorption > policy.poolCapacityLimitKwh) {
    const deviationAmt = round(absorption - policy.poolCapacityLimitKwh, 2);
    return {
      decision: "needs_review",
      deviationReason:
        `Recommended absorption ${absorption} kWh exceeds ` +
        `pool capacity limit ${policy.poolCapacityLimitKwh} kWh ` +
        `by ${deviationAmt} kWh`,
    };
  }

  return { decision: "auto-approved", deviationReason: null };
}

export const DEMO_POLICY: PolicyConfig = {
  bandWidthPercentage: POLICY_BAND_PCT,
  poolCapacityLimitKwh: POLICY_POOL_CAPACITY_LIMIT_KWH,
};
