// DEMO-ONLY — React hook that drives the continuous /demo/live
// simulation. Two intervals: a 4-second meter tick that pushes a new
// reading through the recommend → policy-check pipeline, and an
// exception auto-resolver that approves any queued exception the demo
// operator hasn't clicked Approve on within EXCEPTION_AUTO_RESOLVE_MS.
// In-band recommendations settle immediately; out-of-band ones land in
// the simulated exception queue first. All state is in-memory React
// state, scoped to the page; no Supabase, no Solana.

"use client";

import { useEffect, useReducer, useRef } from "react";
import {
  checkPolicy,
  DEMO_POLICY,
  recommend,
  type PoolState,
  type RecommendResult,
} from "./policy";
import {
  EXCEPTION_AUTO_RESOLVE_MS,
  METER_TICK_MS,
  POOL_STATE,
  SIMULATED_DAY_START_MINUTE,
  SIMULATED_MINUTES_PER_TICK,
  buildAiTrace,
  fakeTxSignature,
  generateMeterNumbers,
  payoutFor,
  randomApprovalReason,
  type AiTrace,
  type Contribution,
  type Exception,
  type MeterReading,
  type Phase,
} from "./sim";

export type LiveDemoState = {
  /** True after the first meter tick has fired. */
  running: boolean;
  minuteOfDay: number;
  meterReadings: MeterReading[];
  contributions: Contribution[];
  exceptions: Exception[];
  cumulativeKwh: number;
  totalEarnedUsd: number;
  /** Counts of in-band vs out-of-band recommendations, for the operator header. */
  inBandCount: number;
  outOfBandCount: number;
  /** Total surplus fed to the grid since page load — the seller meter card's
   *  "Fed to grid today" figure (all readings, settled or not). */
  gridExportTodayKwh: number;
  /** Snapshot of the community pool after the latest tick — drives the
   *  operator view's import/export panel. */
  pool: PoolState;
  /** The most recent AI call (prompt + response + fleet + latency) — the
   *  operator AI panel renders this so the demo shows what the model saw
   *  before the policy check ran. */
  latestAiTrace: AiTrace | null;
};

type Action =
  | { type: "TICK"; reading: MeterReading; contribution: Contribution; aiTrace: AiTrace; pool: PoolState }
  | { type: "ENQUEUE_EXCEPTION"; exception: Exception }
  | { type: "RESOLVE_EXCEPTION"; exceptionId: string; reason: string; txSignature: string }
  | { type: "RESET" };

const INITIAL: LiveDemoState = {
  running: false,
  minuteOfDay: SIMULATED_DAY_START_MINUTE,
  meterReadings: [],
  contributions: [],
  exceptions: [],
  cumulativeKwh: 0,
  totalEarnedUsd: 0,
  inBandCount: 0,
  outOfBandCount: 0,
  gridExportTodayKwh: 0,
  pool: { ...POOL_STATE },
  latestAiTrace: null,
};

function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Run the full recommend → policy-check → settle (if in-band) for one reading. */
function processReading(
  reading: MeterReading,
  pool: typeof POOL_STATE,
): { contribution: Contribution; exception: Exception | null; aiTrace: AiTrace } {
  const rec: RecommendResult = recommend({
    sellerSurplusKwh: reading.kwh,
    timeOfDay: minuteToTime(reading.minuteOfDay),
    pool,
  });
  const policy = checkPolicy(
    { recommendedPrice: rec.recommendedPrice, recommendedAbsorptionKwh: rec.recommendedAbsorptionKwh, direction: rec.direction },
    DEMO_POLICY,
  );

  const aiTrace = buildAiTrace({ reading, pool, recommended: rec });

  const baseContribution: Omit<Contribution, "status" | "txSignature" | "payoutUsd" | "approvalType" | "approvalReason"> = {
    id: uid("c"),
    kwh: reading.kwh,
    recommendedPrice: rec.recommendedPrice,
    finalPrice: rec.recommendedPrice,
    direction: rec.direction,
    decision: policy.decision,
    deviationReason: policy.deviationReason,
    createdAt: new Date().toISOString(),
    minuteOfDay: reading.minuteOfDay,
    aiTrace,
  };

  if (policy.decision === "auto-approved") {
    return {
      contribution: {
        ...baseContribution,
        status: "settled",
        txSignature: fakeTxSignature(),
        payoutUsd: payoutFor(reading.kwh, rec.recommendedPrice),
        approvalType: "auto",
        approvalReason: "Within policy band — auto-approved.",
      },
      exception: null,
      aiTrace,
    };
  }

  return {
    contribution: {
      ...baseContribution,
      status: "exception_queued",
      txSignature: null,
      payoutUsd: 0,
      approvalType: null,
      approvalReason: null,
    },
    exception: {
      id: uid("ex"),
      contributionId: baseContribution.id,
      kwh: reading.kwh,
      recommendedPrice: rec.recommendedPrice,
      direction: rec.direction,
      deviationReason: policy.deviationReason ?? "Outside policy band",
      queuedAt: new Date().toISOString(),
      queuedAtMinute: reading.minuteOfDay,
    },
    aiTrace,
  };
}

function minuteToTime(minute: number): string {
  const h = Math.floor(minute / 60) % 24;
  const m = minute % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function reducer(state: LiveDemoState, action: Action): LiveDemoState {
  switch (action.type) {
    case "TICK": {
      const { reading, contribution, aiTrace, pool } = action;
      const settled = contribution.status === "settled";
      const next: LiveDemoState = {
        ...state,
        running: true,
        minuteOfDay: reading.minuteOfDay,
        // Keep 48 readings — same window the real meter card charts.
        meterReadings: [reading, ...state.meterReadings].slice(0, 48),
        contributions: [contribution, ...state.contributions].slice(0, 30),
        cumulativeKwh: round(state.cumulativeKwh + (settled ? contribution.kwh : 0), 2),
        totalEarnedUsd: round(state.totalEarnedUsd + (settled ? contribution.payoutUsd : 0), 2),
        inBandCount: state.inBandCount + (settled ? 1 : 0),
        outOfBandCount: state.outOfBandCount + (settled ? 0 : 1),
        gridExportTodayKwh: round(state.gridExportTodayKwh + reading.kwh, 2),
        pool,
        latestAiTrace: aiTrace,
      };
      return next;
    }
    case "ENQUEUE_EXCEPTION": {
      return {
        ...state,
        exceptions: [action.exception, ...state.exceptions],
      };
    }
    case "RESOLVE_EXCEPTION": {
      const ex = state.exceptions.find((e) => e.id === action.exceptionId);
      if (!ex) return state;
      const updatedContributions = state.contributions.map((c) =>
        c.id === ex.contributionId
          ? {
              ...c,
              status: "settled" as Phase,
              txSignature: action.txSignature,
              payoutUsd: payoutFor(ex.kwh, ex.recommendedPrice),
              approvalType: "human" as const,
              approvalReason: action.reason,
            }
          : c,
      );
      return {
        ...state,
        exceptions: state.exceptions.filter((e) => e.id !== action.exceptionId),
        contributions: updatedContributions,
        cumulativeKwh: round(state.cumulativeKwh + ex.kwh, 2),
        totalEarnedUsd: round(
          state.totalEarnedUsd + payoutFor(ex.kwh, ex.recommendedPrice),
          2,
        ),
      };
    }
    case "RESET":
      return { ...INITIAL };
  }
}

function round(n: number, decimals: number): number {
  const m = 10 ** decimals;
  return Math.round(n * m) / m;
}

export function useLiveDemo() {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const minuteRef = useRef(SIMULATED_DAY_START_MINUTE);
  const poolRef = useRef({ ...POOL_STATE });

  // 4-second meter tick — runs recommend + policy-check, enqueues exceptions
  useEffect(() => {
    const id = setInterval(() => {
      minuteRef.current = (minuteRef.current + SIMULATED_MINUTES_PER_TICK) % (24 * 60);
      const reading: MeterReading = {
        id: uid("m"),
        ...generateMeterNumbers(minuteRef.current),
        minuteOfDay: minuteRef.current,
        createdAt: new Date().toISOString(),
      };
      const { contribution, exception, aiTrace } = processReading(reading, poolRef.current);
      // advance the pool a little so the simulation feels alive
      if (contribution.direction === "local_pool") {
        poolRef.current.currentAbsorptionKwh = round(
          Math.min(
            poolRef.current.absorptionLimitKwh,
            poolRef.current.currentAbsorptionKwh + contribution.kwh * 0.4,
          ),
          2,
        );
      }
      dispatch({ type: "TICK", reading, contribution, aiTrace, pool: { ...poolRef.current } });
      if (exception) {
        dispatch({ type: "ENQUEUE_EXCEPTION", exception });
      }
    }, METER_TICK_MS);
    return () => clearInterval(id);
  }, []);

  // 1-second sweep that auto-resolves any exception the operator hasn't
  // clicked Approve on within the auto-resolve window
  useEffect(() => {
    const id = setInterval(() => {
      const now = Date.now();
      state.exceptions.forEach((ex) => {
        if (now - new Date(ex.queuedAt).getTime() >= EXCEPTION_AUTO_RESOLVE_MS) {
          dispatch({
            type: "RESOLVE_EXCEPTION",
            exceptionId: ex.id,
            reason: randomApprovalReason(),
            txSignature: fakeTxSignature(),
          });
        }
      });
    }, 1_000);
    return () => clearInterval(id);
  }, [state.exceptions]);

  return {
    state,
    /** Manual operator approval — same RESOLVE path the auto-resolver uses,
     *  so the contribution settles with approvalType "human" and a tx sig.
     *  Lets a presenter click Approve in the exception queue instead of
     *  waiting out the auto-resolve timer. */
    approveException: (exceptionId: string) => {
      dispatch({
        type: "RESOLVE_EXCEPTION",
        exceptionId,
        reason: "Approved by operator — price acceptable for current pool conditions.",
        txSignature: fakeTxSignature(),
      });
    },
    reset: () => {
      minuteRef.current = SIMULATED_DAY_START_MINUTE;
      poolRef.current = { ...POOL_STATE };
      dispatch({ type: "RESET" });
    },
  };
}
