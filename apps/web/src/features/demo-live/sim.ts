// DEMO-ONLY — purely client-side simulation helpers for /demo/live.
// No DB writes, no Solana calls, no Supabase. All randomness is for
// the demo. The fake tx signature clearly is not a real devnet tx —
// it's a base58-looking string that the demo displays as-is.

import type { FleetOutlookData } from "@/app/operator/dashboard/fleet-outlook";
import {
  FEED_IN_TARIFF,
  POOL_ABSORPTION_LIMIT_KWH,
  POOL_BASE_CONSUMPTION_KWH,
  POLICY_FEED_IN_REFERENCE,
  POLICY_OPERATOR_MARGIN_PCT,
  POLICY_POOL_CAPACITY_LIMIT_KWH,
  POLICY_SELLER_UPLIFT_PCT,
} from "./policy";

// Base58 alphabet (Bitcoin / Solana standard) — used to make the fake
// tx signature *look* like a real one without being one.
const BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

// AI model identifiers — mirror what apps/api/app/services/recommender.py
// uses. The real code picks `groq` when GROQ_API_KEY is set, else `rules`.
// In /demo/live we don't call out to Groq, so the displayed model reflects
// the same fallback the API would use in this environment.
export const GROQ_MODEL_NAME = "mixtral-8x7b-32768";
export const GROQ_MODEL_LABEL = `Groq / ${GROQ_MODEL_NAME}`;
export const RULES_MODEL_LABEL = "Rules estimator (no GROQ_API_KEY)";

// A fake "connected seller wallet" used purely for the visual wallet panel.
// Stable across the page lifecycle (not random) so the truncated pubkey
// doesn't shuffle on every render. Clearly not a real devnet address —
// starts with DEMO so it can't ever collide with a real key.
export const DEMO_SELLER_PUBKEY = "DEMOS1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX";
// Fake operator wallet — used to show "operator paid seller" with a
// readable counterparty address.
export const DEMO_OPERATOR_PUBKEY = "DEMOOXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXOPR";

// Devnet explorer URL builder. The link is displayed as-is and will not
// resolve (the fake sig is not a real tx). It still looks right.
export function demoExplorerUrl(sig: string): string {
  return `https://explorer.solana.com/tx/${sig}?cluster=devnet`;
}

/** Convert lamports → SOL with a fixed 9-decimal display. */
export function lamportsToSol(lamports: number): string {
  return (lamports / 1_000_000_000).toFixed(9);
}

export type Direction = "local_pool" | "import" | "export";

export type Phase =
  | "meter_reading"
  | "ai_recommending"
  | "policy_checking"
  | "auto_approved"
  | "exception_queued"
  | "exception_resolving"
  | "settled";

export type MeterReading = {
  id: string;
  /** Plausible surplus kWh contribution, 5–50 range with occasional bursts. */
  kwh: number;
  /** Total panel generation for the interval — surplus + household consumption.
   *  Mirrors generation_kwh in components/meter-section.tsx. */
  generationKwh: number;
  /** Simulated household consumption for the interval. */
  consumptionKwh: number;
  /** Simulated minute-of-day the reading "arrived" at. */
  minuteOfDay: number;
  createdAt: string;
};

/** Per-contribution AI call trace. The real API at
 *  apps/api/app/services/recommender.py builds a similar prompt, calls
 *  Groq with response_format=json_object, and falls back to a rules
 *  estimator on failure. We replicate that here purely for the visual
 *  AI panel — no actual network call is made. */
export type AiTrace = {
  /** "groq" if GROQ_API_KEY were set (production path), "rules" otherwise. */
  modelUsed: "groq" | "rules";
  /** Display label, e.g. "Groq / mixtral-8x7b-32768" or "Rules estimator". */
  modelLabel: string;
  /** Pool + reading context that was passed to the model. */
  prompt: string;
  /** Raw JSON the model "returned" (or the rules estimator produced). */
  rawResponse: string;
  /** Optional fleet context blob shown in the panel. */
  fleetContext: { netPositionKwh: number } | null;
  /** Wall-clock-style simulated latency in ms. */
  latencyMs: number;
};

export type Contribution = {
  id: string;
  kwh: number;
  recommendedPrice: number;
  finalPrice: number;
  direction: Direction;
  decision: "auto-approved" | "needs_review";
  /** Present only when decision === "needs_review". */
  deviationReason: string | null;
  /** Set when the operator (or auto-resolver) approves. */
  approvalType: "auto" | "human" | null;
  approvalReason: string | null;
  status: Phase;
  /** Fake base58-looking tx signature, set when the contribution settles. */
  txSignature: string | null;
  payoutUsd: number;
  createdAt: string;
  /** Minute-of-day the reading was submitted; preserved for the activity feed. */
  minuteOfDay: number;
  /** Snapshot of the AI call that produced this recommendation. */
  aiTrace: AiTrace;
};

export type Exception = {
  id: string;
  contributionId: string;
  kwh: number;
  recommendedPrice: number;
  direction: Direction;
  deviationReason: string;
  queuedAt: string;
  /** Minute of the demo clock at which it was queued. */
  queuedAtMinute: number;
};

export const METER_TICK_MS = 4_000;            // spec: every 4 seconds
export const EXCEPTION_AUTO_RESOLVE_MS = 8_000; // auto-resolve fallback; the demo operator can also click Approve

// Fake meter device id shown in the seller view header — mirrors the mono
// device-id label in components/meter-section.tsx. Clearly demo-prefixed.
export const DEMO_METER_DEVICE_ID = "GR-DEMO-0042";
export const SIMULATED_DAY_START_MINUTE = 9 * 60; // 09:00 simulated start
export const SIMULATED_MINUTES_PER_TICK = 10;   // 10 simulated minutes per tick

export const POOL_STATE: {
  currentAbsorptionKwh: number;
  absorptionLimitKwh: number;
  currentConsumptionKwh: number;
} = {
  currentAbsorptionKwh: 30,
  absorptionLimitKwh: POOL_ABSORPTION_LIMIT_KWH,
  currentConsumptionKwh: POOL_BASE_CONSUMPTION_KWH,
};

/** Pull a plausible kWh reading — base 5–50 with occasional bursts and
 *  small time-of-day multipliers so the demo doesn't look uniform. */
export function generateReading(minuteOfDay: number, rand: () => number = Math.random): number {
  // Time-of-day multiplier: gentle bump midday, lighter morning/late afternoon
  const hour = Math.floor(minuteOfDay / 60) + minuteOfDay / 60 - Math.floor(minuteOfDay / 60);
  const tod = 0.85 + 0.3 * Math.sin(((hour - 6) / 12) * Math.PI); // peaks ~12:00
  const burst = rand() < 0.08 ? 1.6 + rand() * 0.6 : 1.0;       // ~8% oversized events
  const base = 5 + rand() * 45;                                  // 5..50
  return round(Math.max(1, base * tod * burst), 2);
}

/** Full simulated meter numbers for one interval: surplus (kwh) plus the
 *  generation/consumption split the real meter card displays. Consumption
 *  is 25–60% on top of the surplus; generation is the sum, so the numbers
 *  are always internally consistent (generation − consumption = surplus). */
export function generateMeterNumbers(
  minuteOfDay: number,
  rand: () => number = Math.random,
): Pick<MeterReading, "kwh" | "generationKwh" | "consumptionKwh"> {
  const kwh = generateReading(minuteOfDay, rand);
  const consumptionKwh = round(kwh * (0.25 + rand() * 0.35), 2);
  const generationKwh = round(kwh + consumptionKwh, 2);
  return { kwh, generationKwh, consumptionKwh };
}

/** Random base58-looking string of length 86–88 (a typical Solana tx sig). */
export function fakeTxSignature(rand: () => number = Math.random): string {
  const len = 86 + Math.floor(rand() * 3);
  let s = "";
  for (let i = 0; i < len; i++) s += BASE58[Math.floor(rand() * BASE58.length)];
  return s;
}

/** Realistic-feeling operator-approval reason strings, picked at random. */
const APPROVAL_REASONS = [
  "Within policy band — approved at AI-recommended price.",
  "Price within ±10% of reference tariff; absorption within pool cap.",
  "Auto-approved: band check passed, capacity check passed.",
  "Approved: deviation is inside the configured band width.",
  "Approved: surplus absorbed by community pool, no export needed.",
  "Pool capacity available, local absorption path approved.",
];

export function randomApprovalReason(rand: () => number = Math.random): string {
  return APPROVAL_REASONS[Math.floor(rand() * APPROVAL_REASONS.length)];
}

/** Build a snapshot of the AI call that produced a recommendation. The
 *  shape mirrors what apps/api/app/services/recommender.py would log
 *  in production: model name, the prompt, the raw JSON response, fleet
 *  context, and latency. We use "rules" (the fallback) since this demo
 *  has no GROQ_API_KEY in the env — which matches what the API would
 *  actually return in this environment. */
export function buildAiTrace(args: {
  reading: MeterReading;
  pool: { currentAbsorptionKwh: number; absorptionLimitKwh: number; currentConsumptionKwh: number };
  recommended: { recommendedPrice: number; recommendedAbsorptionKwh: number; direction: Direction };
  rand?: () => number;
}): AiTrace {
  const rand = args.rand ?? Math.random;
  const timeOfDay = (() => {
    const h = Math.floor(args.reading.minuteOfDay / 60) % 24;
    const m = args.reading.minuteOfDay % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  })();

  // Production: rules fallback fires when GROQ_API_KEY is missing. The
  // live demo has no env injection, so we use the rules model — same as
  // what the real API would do here.
  const modelUsed = "rules" as const;

  const prompt =
    `Given a solar energy seller with ${args.reading.kwh} kWh surplus ` +
    `at ${timeOfDay}, ` +
    `pool currently absorbing ${args.pool.currentAbsorptionKwh} kWh ` +
    `with a limit of ${args.pool.absorptionLimitKwh} kWh, ` +
    `and community consuming ${args.pool.currentConsumptionKwh} kWh, ` +
    `determine the direction: ` +
    `'local_pool' (surplus absorbed by community), ` +
    `'import' (shortfall — community consumes more than pool has), ` +
    `or 'export' (surplus exceeds pool capacity). ` +
    `Recommend a sell price (in $/kWh) and how much of the surplus the pool should absorb. ` +
    `Respond with only a JSON object: ` +
    `{"direction": "<str>", "recommended_price": <float>, "recommended_absorption_kwh": <float>}`;

  const rawResponse = JSON.stringify(
    {
      direction: args.recommended.direction,
      recommended_price: args.recommended.recommendedPrice,
      recommended_absorption_kwh: args.recommended.recommendedAbsorptionKwh,
    },
    null,
    2,
  );

  // Tiny synthetic fleet nudge so the panel has something to show.
  const netPositionKwh = Math.round((rand() * 60 - 30) * 10) / 10;

  // Rules estimator is deterministic and fast — show that explicitly.
  const latencyMs = 8 + Math.floor(rand() * 12);

  return {
    modelUsed,
    modelLabel: RULES_MODEL_LABEL,
    prompt,
    rawResponse,
    fleetContext: { netPositionKwh },
    latencyMs,
  };
}

// ---------------------------------------------------------------------------
// Fleet outlook — synthetic data for the real <FleetOutlook /> component
// (app/operator/dashboard/fleet-outlook.tsx, pure presentational). The demo
// feeds it a deterministic 24h forecast derived from the simulated clock so
// the operator view shows the same Phase-4 section as the real dashboard.
// ---------------------------------------------------------------------------

// Simulated fleet roster shown in the per-seller breakdown. The first row is
// the demo seller whose meter drives the page; the others are community
// peers that exist only in this forecast.
const DEMO_FLEET_SELLERS = [
  { seller_id: "demo-seller-001 (you)", share: 0.46, mean_confidence: 0.84 },
  { seller_id: "community-seller-014", share: 0.33, mean_confidence: 0.78 },
  { seller_id: "community-seller-032", share: 0.21, mean_confidence: 0.69 },
];

/** Solar output factor for an hour of day: 0 at night, peaking ~13:00. */
function solarFactor(hour: number): number {
  if (hour < 6 || hour > 19) return 0;
  return Math.max(0, Math.sin(((hour - 6) / 13) * Math.PI));
}

/** Expected community demand for an hour: flat base + morning/evening bumps. */
function demandForHour(hour: number): number {
  let d = 38;
  if (hour >= 7 && hour <= 9) d += 6;   // morning routine
  if (hour >= 18 && hour <= 22) d += 14; // evening peak
  return d;
}

/** Deterministic 24h fleet outlook anchored at the simulated clock. Same
 *  shape as GET /api/v1/operator/fleet so the real FleetOutlook component
 *  renders it unchanged. */
export function buildFleetOutlook(minuteOfDay: number): FleetOutlookData {
  const startHour = Math.floor(minuteOfDay / 60) % 24;
  const now = Date.now();
  const FLEET_PEAK_KWH = 72; // fleet-wide predicted surplus at solar noon

  const hourly = Array.from({ length: 24 }, (_, i) => {
    const hour = (startHour + i) % 24;
    const predicted = round(FLEET_PEAK_KWH * solarFactor(hour), 1);
    const demand = demandForHour(hour);
    return {
      forecast_for: new Date(now + i * 3_600_000).toISOString(),
      predicted_surplus_kwh: predicted,
      lower_kwh: round(predicted * 0.8, 1),
      upper_kwh: round(predicted * 1.2, 1),
      expected_demand_kwh: demand,
      net_position_kwh: round(predicted - demand, 1),
    };
  });

  const totalSupply = round(hourly.reduce((s, h) => s + h.predicted_surplus_kwh, 0), 1);
  const totalDemand = round(hourly.reduce((s, h) => s + h.expected_demand_kwh, 0), 1);
  const net = round(totalSupply - totalDemand, 1);

  return {
    horizon_hours: 24,
    total_predicted_surplus_kwh: totalSupply,
    total_expected_demand_kwh: totalDemand,
    net_position_kwh: net,
    summary:
      net >= 0
        ? `Fleet is expected to run a ${net.toFixed(1)} kWh surplus over the next 24h. Solar peaks near midday; demand rises after 18:00 — consider exporting the midday excess.`
        : `Fleet is expected to run a ${Math.abs(net).toFixed(1)} kWh shortfall over the next 24h. Demand outpaces solar after 18:00 — imports likely during the evening peak.`,
    hourly,
    per_seller: DEMO_FLEET_SELLERS.map((s) => ({
      seller_id: s.seller_id,
      total_predicted_kwh: round(totalSupply * s.share, 1),
      mean_confidence: s.mean_confidence,
    })),
    drift_flags: [
      { seller_id: "community-seller-032", mean_abs_delta_kwh: 3.4, scored_count: 18 },
    ],
  };
}

function round(n: number, decimals: number): number {
  const m = 10 ** decimals;
  return Math.round(n * m) / m;
}

/** Total payout the seller earns for a contribution, in USD. Mirrors the
 *  architecture's "seller payout = feed-in tariff + uplift %" rule, with
 *  the operator margin netted out as a flat per-kWh fee. */
export function payoutFor(kwh: number, finalPrice: number): number {
  return round(kwh * finalPrice, 2);
}

export {
  FEED_IN_TARIFF,
  POLICY_FEED_IN_REFERENCE,
  POLICY_SELLER_UPLIFT_PCT,
  POLICY_OPERATOR_MARGIN_PCT,
  POLICY_POOL_CAPACITY_LIMIT_KWH,
};
