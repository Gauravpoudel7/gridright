// DEMO-ONLY: safe to delete — remove this file along with src/features/demo/, src/app/demo/, and the "Try the Demo" button on src/app/page.tsx
"use client";

import { useReducer, useEffect, useRef } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { payDemoSeller } from "@/app/actions/demo-payout";
import { useDemoMeter, type DemoMeter } from "./use-demo-meter";
import {
  describeStep,
  DEMO_AI_PRICE,
  DEMO_ADJUSTED_PRICE,
  type DemoStep,
  type DemoContribution,
} from "./mock-data";

export type DemoRole = "seller" | "operator";

type DemoState = {
  step: DemoStep;
  activeCase: "auto" | "review";
  role: DemoRole;
  /** kWh captured from the meter at submit time — drives the whole scenario. */
  submittedKwh: number;
  aiPrice: number;
  finalPrice: number;
  sellerBalance: number;
  operatorBalance: number;
  poolKwh: number;
  contributions: DemoContribution[];
  /** Real devnet settlement result recorded at payment_confirmed. */
  txSignature: string | null;
  explorerUrl: string | null;
  /** The seller pubkey that actually received the payout (set by SETTLE). */
  settledSeller: string | null;
  /** Set when the real devnet transfer failed and we fell back to simulation. */
  payoutError: string | null;
};

type DemoAction =
  | { type: "ADVANCE"; submittedKwh?: number }
  | {
      type: "SETTLE";
      txSignature: string | null;
      explorerUrl: string | null;
      settledSeller: string | null;
      payoutError: string | null;
    }
  | { type: "SET_CASE"; case: "auto" | "review" }
  | { type: "SET_ROLE"; role: DemoRole }
  | { type: "RESET" };

const INITIAL: DemoState = {
  step: "idle",
  activeCase: "auto",
  role: "seller",
  submittedKwh: 0,
  aiPrice: DEMO_AI_PRICE,
  finalPrice: DEMO_AI_PRICE,
  sellerBalance: 0,
  operatorBalance: 500,
  poolKwh: 0,
  contributions: [],
  txSignature: null,
  explorerUrl: null,
  settledSeller: null,
  payoutError: null,
};

const AUTO_SEQUENCE: DemoStep[] = [
  "idle",
  "surplus_submitted",
  "ai_recommending",
  "auto_approved",
  "payment_sending",
  "payment_confirmed",
];

const REVIEW_SEQUENCE: DemoStep[] = [
  "idle",
  "surplus_submitted",
  "ai_recommending",
  "flagged_review",
  "operator_reviewing",
  "operator_approved",
  "payment_sending",
  "payment_confirmed",
];

export function sequenceFor(activeCase: "auto" | "review"): DemoStep[] {
  return activeCase === "auto" ? AUTO_SEQUENCE : REVIEW_SEQUENCE;
}

/** Apply the settlement bookkeeping (balances + contribution row) for the
 *  confirmed payment. `settle` carries the real devnet result (or the
 *  simulated fallback when the on-chain transfer failed). */
function applySettlement(
  state: DemoState,
  settle: {
    txSignature: string | null;
    explorerUrl: string | null;
    settledSeller: string | null;
    payoutError: string | null;
  },
): DemoState {
  const payout = Math.round(state.submittedKwh * state.finalPrice * 100) / 100;
  const sellerBalance = Math.round((state.sellerBalance + payout) * 100) / 100;
  const operatorBalance = Math.round((state.operatorBalance - payout) * 100) / 100;
  const txSignature =
    settle.txSignature ?? `DEMO_TX_${Math.random().toString(36).slice(2, 10).toUpperCase()}`;
  return {
    ...state,
    step: "payment_confirmed",
    sellerBalance,
    operatorBalance,
    txSignature,
    explorerUrl: settle.explorerUrl,
    settledSeller: settle.settledSeller,
    payoutError: settle.payoutError,
    contributions: [
      ...state.contributions,
      {
        id: `demo-${Date.now()}`,
        kwh: state.submittedKwh,
        aiPrice: state.aiPrice,
        finalPrice: state.finalPrice,
        status: "settled",
        txSignature,
        case: state.activeCase,
      },
    ],
  };
}

function reducer(state: DemoState, action: DemoAction): DemoState {
  if (action.type === "RESET") return { ...INITIAL, activeCase: state.activeCase, role: state.role };
  if (action.type === "SET_CASE") return { ...INITIAL, activeCase: action.case, role: state.role };
  if (action.type === "SET_ROLE") return { ...state, role: action.role };
  if (action.type === "SETTLE") return applySettlement(state, action);

  const seq = sequenceFor(state.activeCase);
  const idx = seq.indexOf(state.step);
  const next = seq[idx + 1] ?? state.step;

  // payment_confirmed is only reached via SETTLE (after the real devnet
  // transfer resolves), never via a bare ADVANCE.
  if (next === "payment_confirmed") return state;

  let { submittedKwh, finalPrice, poolKwh } = state;

  if (next === "surplus_submitted") {
    // Surplus figure comes from the live meter (passed in the action), never
    // a hardcoded literal.
    submittedKwh = action.submittedKwh ?? 0;
    poolKwh = Math.round((state.poolKwh + submittedKwh) * 100) / 100;
  }
  if (next === "operator_approved") {
    finalPrice = DEMO_ADJUSTED_PRICE; // operator nudged the price up
  }

  return { ...state, step: next, submittedKwh, finalPrice, poolKwh };
}

export type DemoScenario = {
  state: DemoState;
  meter: DemoMeter;
  stepInfo: { label: string; detail: string };
  isFinished: boolean;
  advance: () => void;
  reset: () => void;
  setCase: (c: "auto" | "review") => void;
  setRole: (r: DemoRole) => void;
};

export function useDemoState(): DemoScenario {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const meter = useDemoMeter();
  // The seller's connected wallet (devnet). When set, the demo's real devnet
  // transfer lands in *their* account — so they can verify the payout in
  // Phantom. When null, the server action falls back to the env default.
  const { publicKey: sellerWallet } = useWallet();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const advance = () => {
    // Submitting is the one transition that pulls a value out of the meter.
    const seq = sequenceFor(state.activeCase);
    const next = seq[seq.indexOf(state.step) + 1];
    if (next === "surplus_submitted") {
      dispatch({ type: "ADVANCE", submittedKwh: meter.consumeAvailableSurplus() });
    } else {
      dispatch({ type: "ADVANCE" });
    }
  };

  const reset = () => {
    meter.reset();
    dispatch({ type: "RESET" });
  };

  const setCase = (c: "auto" | "review") => {
    meter.reset();
    dispatch({ type: "SET_CASE", case: c });
  };

  const setRole = (r: DemoRole) => dispatch({ type: "SET_ROLE", role: r });

  // Auto-advance through "processing" steps. payment_sending is special: it
  // fires a REAL devnet transfer (operator → seller) and only advances to
  // payment_confirmed once the transaction resolves, recording the real
  // signature. All other processing steps just tick forward on a timer.
  useEffect(() => {
    if (state.step === "payment_sending") {
      let cancelled = false;
      void payDemoSeller(sellerWallet?.toBase58()).then((r) => {
        if (cancelled) return;
        dispatch({
          type: "SETTLE",
          txSignature: r.ok ? r.signature ?? null : null,
          explorerUrl: r.ok ? r.explorerUrl ?? null : null,
          settledSeller: r.ok ? r.seller ?? null : null,
          payoutError: r.ok ? null : r.error ?? "Devnet transfer failed",
        });
      });
      return () => {
        cancelled = true;
      };
    }

    const autoSteps: DemoStep[] = ["ai_recommending", "operator_reviewing"];
    if (autoSteps.includes(state.step)) {
      timerRef.current = setTimeout(() => dispatch({ type: "ADVANCE" }), 1800);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [state.step, sellerWallet]);

  const seq = sequenceFor(state.activeCase);
  const isFinished = state.step === seq[seq.length - 1];
  const stepInfo = describeStep(state.step, {
    availableKwh: meter.availableSurplusKwh,
    submittedKwh: state.submittedKwh,
    finalPrice: state.finalPrice,
  });

  return { state, meter, stepInfo, isFinished, advance, reset, setCase, setRole };
}
