// DEMO-ONLY: safe to delete — remove this file along with src/features/demo/, src/app/demo/, and the "Try the Demo" button on src/app/page.tsx
"use client";

import Link from "next/link";
import { useDemoState, sequenceFor, type DemoRole } from "@/features/demo/use-demo-state";
import { MeterTileView } from "@/features/demo/demo-meter-tile";
import { MOCK_SELLER_WALLET, MOCK_OPERATOR_WALLET } from "@/features/demo/mock-data";
import type { DemoMeter } from "@/features/demo/use-demo-meter";

function WalletBox({ label, address, balance }: { label: string; address: string; balance: number }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="font-mono text-xs text-zinc-700 dark:text-zinc-300">{address}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">${balance.toFixed(2)}</p>
    </div>
  );
}

/** Seller-facing status line for the current scenario step. */
function sellerStatus(step: string): { label: string; tone: string } {
  switch (step) {
    case "idle":
      return { label: "Surplus available — ready to list", tone: "zinc" };
    case "surplus_submitted":
      return { label: "Submitted to pool", tone: "blue" };
    case "ai_recommending":
      return { label: "Awaiting AI price", tone: "blue" };
    case "auto_approved":
      return { label: "Auto-approved", tone: "green" };
    case "flagged_review":
    case "operator_reviewing":
      return { label: "Pending operator review", tone: "yellow" };
    case "operator_approved":
      return { label: "Approved by operator", tone: "green" };
    case "payment_sending":
      return { label: "Payment on the way", tone: "blue" };
    case "payment_confirmed":
      return { label: "Payment received ✓", tone: "green" };
    default:
      return { label: step, tone: "zinc" };
  }
}

const TONE: Record<string, string> = {
  zinc: "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400",
  blue: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  green: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  yellow: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
};

/** Seller perspective: own meter, listing status, own wallet balance. */
function SellerView({
  meter,
  status,
  sellerBalance,
  submittedKwh,
  finalPrice,
  step,
  txSignature,
  explorerUrl,
  settledSeller,
  payoutError,
}: {
  meter: DemoMeter;
  status: { label: string; tone: string };
  sellerBalance: number;
  submittedKwh: number;
  finalPrice: number;
  step: string;
  txSignature: string | null;
  explorerUrl: string | null;
  settledSeller: string | null;
  payoutError: string | null;
}) {
  const paid = step === "payment_confirmed";
  return (
    <div className="space-y-4">
      <MeterTileView meter={meter} />

      <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">My listing</p>
          <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${TONE[status.tone]}`}>
            {status.label}
          </span>
        </div>
        <p className="text-xs text-zinc-500 tabular-nums">
          {submittedKwh > 0
            ? `Listed ${submittedKwh.toFixed(2)} kWh${paid ? ` @ $${finalPrice.toFixed(4)}/kWh` : ""}`
            : "Nothing listed yet — surplus is still accumulating on the meter."}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4">
        <WalletBox
          label="My wallet (seller)"
          address={settledSeller ?? MOCK_SELLER_WALLET}
          balance={sellerBalance}
        />
      </div>

      {paid && (
        <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
          <p className="mb-1 text-xs font-medium text-zinc-500">Settlement transaction</p>
          {txSignature && !payoutError ? (
            <>
              <p className="break-all font-mono text-xs text-zinc-700 dark:text-zinc-300">{txSignature}</p>
              {settledSeller && (
                <p className="mt-1 text-xs text-zinc-500">
                  → <span className="font-mono">{settledSeller}</span>
                </p>
              )}
              {explorerUrl && (
                <a
                  href={explorerUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-block text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  View on Solana Explorer (devnet) ↗
                </a>
              )}
            </>
          ) : (
            <p className="text-xs text-yellow-700 dark:text-yellow-400">
              Devnet transfer unavailable — showing a simulated confirmation.
              {payoutError ? ` (${payoutError})` : ""}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** Operator perspective: AI recommendation + approve/review panel driven by
 *  the seller's actual submitted surplus, plus operator wallet and pool. */
function OperatorView({
  submittedKwh,
  aiPrice,
  finalPrice,
  operatorBalance,
  poolKwh,
  activeCase,
  step,
}: {
  submittedKwh: number;
  aiPrice: number;
  finalPrice: number;
  operatorBalance: number;
  poolKwh: number;
  activeCase: "auto" | "review";
  step: string;
}) {
  const hasListing = submittedKwh > 0;
  const flagged = ["flagged_review", "operator_reviewing", "operator_approved"].includes(step);
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <p className="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">AI recommendation</p>
        {!hasListing ? (
          <p className="text-xs text-zinc-500">Waiting for a seller to list surplus…</p>
        ) : (
          <div className="space-y-1 text-sm text-zinc-700 dark:text-zinc-300 tabular-nums">
            <p>
              Incoming surplus: <span className="font-semibold">{submittedKwh.toFixed(2)} kWh</span>
            </p>
            <p>
              AI recommended price: <span className="font-semibold">${aiPrice.toFixed(4)}/kWh</span>
            </p>
            {flagged ? (
              <p className="text-yellow-700 dark:text-yellow-400">
                Outside policy band — needs operator review. Adjusted to ${finalPrice.toFixed(4)}/kWh.
              </p>
            ) : (
              <p className="text-green-700 dark:text-green-400">
                Within policy band — {activeCase === "auto" ? "auto-approved" : "pending"}.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <p className="text-xs font-medium text-zinc-500">Community pool</p>
        <p className="text-lg font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">{poolKwh.toFixed(2)} kWh</p>
      </div>

      <WalletBox label="Operator wallet" address={MOCK_OPERATOR_WALLET} balance={operatorBalance} />
    </div>
  );
}

export default function DemoPage() {
  const { state, meter, stepInfo, isFinished, advance, reset, setCase, setRole } = useDemoState();
  const seq = sequenceFor(state.activeCase);
  const progress = (seq.indexOf(state.step) / (seq.length - 1)) * 100;
  const isProcessing = ["ai_recommending", "payment_sending", "operator_reviewing"].includes(state.step);
  const status = sellerStatus(state.step);

  return (
    <div className="mx-auto w-full max-w-2xl px-6 py-12">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <span className="mb-1 inline-block rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            DEMO — settles with a real devnet SOL transfer
          </span>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">GridRight Demo</h1>
        </div>
        <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-50">
          ← Back to home
        </Link>
      </div>

      {/* Role toggle */}
      <div className="mb-6 inline-flex rounded-lg border border-zinc-200 p-1 dark:border-zinc-800">
        {(["seller", "operator"] as const).map((r) => (
          <button
            key={r}
            onClick={() => setRole(r)}
            className={`rounded px-4 py-1.5 text-sm font-medium capitalize transition-colors ${
              state.role === r
                ? "bg-zinc-900 text-zinc-50 dark:bg-zinc-50 dark:text-zinc-900"
                : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
            }`}
          >
            {r} view
          </button>
        ))}
      </div>

      {/* Case selector */}
      <div className="mb-6 flex gap-2">
        {(["auto", "review"] as const).map((c) => (
          <button
            key={c}
            onClick={() => setCase(c)}
            className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              state.activeCase === c
                ? "bg-zinc-900 text-zinc-50 dark:bg-zinc-50 dark:text-zinc-900"
                : "border border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300"
            }`}
          >
            {c === "auto" ? "Auto-approve case" : "Operator review case"}
          </button>
        ))}
      </div>

      {/* Progress bar */}
      <div className="mb-6 h-2 w-full rounded-full bg-zinc-100 dark:bg-zinc-800">
        <div className="h-2 rounded-full bg-green-500 transition-all duration-500" style={{ width: `${progress}%` }} />
      </div>

      {/* Step card (shared timeline, same underlying state for both roles) */}
      <div className="mb-6 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-1 flex items-center gap-2">
          <p className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">{stepInfo.label}</p>
          {isProcessing && (
            <span className="inline-flex h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-700" />
          )}
        </div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">{stepInfo.detail}</p>
      </div>

      {state.role === "seller" ? (
        <SellerView
          meter={meter}
          status={status}
          sellerBalance={state.sellerBalance}
          submittedKwh={state.submittedKwh}
          finalPrice={state.finalPrice}
          step={state.step}
          txSignature={state.txSignature}
          explorerUrl={state.explorerUrl}
          settledSeller={state.settledSeller}
          payoutError={state.payoutError}
        />
      ) : (
        <OperatorView
          submittedKwh={state.submittedKwh}
          aiPrice={state.aiPrice}
          finalPrice={state.finalPrice}
          operatorBalance={state.operatorBalance}
          poolKwh={state.poolKwh}
          activeCase={state.activeCase}
          step={state.step}
        />
      )}

      {/* Controls */}
      <div className="mt-6 flex gap-3">
        {!isFinished && !isProcessing && state.role === "seller" && ["idle"].includes(state.step) && (
          <button
            onClick={advance}
            className="rounded bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-50 hover:bg-zinc-700 dark:bg-zinc-50 dark:text-zinc-900"
          >
            List surplus →
          </button>
        )}
        {!isFinished && !isProcessing && !["idle"].includes(state.step) && (
          <button
            onClick={advance}
            className="rounded bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-50 hover:bg-zinc-700 dark:bg-zinc-50 dark:text-zinc-900"
          >
            Next step →
          </button>
        )}
        <button
          onClick={reset}
          className="rounded border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
