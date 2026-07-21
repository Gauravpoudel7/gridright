// DEMO-ONLY — public, no-auth, continuously-simulated twin of the
// seller + operator experience. Lives at /demo/live so it does not
// collide with the existing click-through /demo page. All simulation
// runs client-side in React state via useLiveDemo — no Supabase, no
// Solana, no backend calls. The page resets on reload.

"use client";

import { useState } from "react";
import { DemoBanner } from "@/features/demo-live/demo-banner";
import { OperatorView } from "@/features/demo-live/operator-view";
import { SellerView } from "@/features/demo-live/seller-view";
import { useLiveDemo } from "@/features/demo-live/use-live-demo";

type Role = "seller" | "operator";

export default function LiveDemoPage() {
  const [role, setRole] = useState<Role>("seller");
  const { state, approveException, reset } = useLiveDemo();
  const isOperator = role === "operator";

  return (
    // Same container widths as the real pages: seller dashboard is
    // max-w-4xl, operator dashboard is max-w-6xl.
    <div className={`mx-auto w-full ${isOperator ? "max-w-6xl" : "max-w-4xl"} px-6 py-12`}>
      <DemoBanner />

      {/* Header — same layout as the real dashboards: title + "signed in
          as" on the left, session controls on the right (the role toggle
          and Reset stand in for Sign out). */}
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {isOperator ? "Operator dashboard" : "Seller dashboard"}
          </h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Signed in as demo-{role}@gridright.demo · simulated session
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg border border-zinc-200 p-1 dark:border-zinc-800">
            {(["seller", "operator"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRole(r)}
                className={`rounded px-4 py-1.5 text-sm font-medium capitalize transition-colors ${
                  role === r
                    ? "bg-zinc-900 text-zinc-50 dark:bg-zinc-50 dark:text-zinc-900"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          <button
            onClick={reset}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-900 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
          >
            Reset
          </button>
        </div>
      </header>

      {role === "seller" ? (
        <SellerView
          contributions={state.contributions}
          cumulativeKwh={state.cumulativeKwh}
          totalEarnedUsd={state.totalEarnedUsd}
          meterReadings={state.meterReadings}
          gridExportTodayKwh={state.gridExportTodayKwh}
          simulatedMinute={state.minuteOfDay}
          running={state.running}
        />
      ) : (
        <OperatorView
          contributions={state.contributions}
          exceptions={state.exceptions}
          cumulativeKwh={state.cumulativeKwh}
          totalEarnedUsd={state.totalEarnedUsd}
          pool={state.pool}
          simulatedMinute={state.minuteOfDay}
          latestAiTrace={state.latestAiTrace}
          onApproveException={approveException}
        />
      )}

      <footer className="mt-10 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        Demo policy band: ±10% around the $0.10/kWh feed-in tariff. In-band
        recommendations auto-approve and settle instantly; out-of-band ones
        land in the operator&apos;s exception queue, where you can click
        Approve — or wait ~8s for the auto-resolver. All state is in-memory;
        reload or Reset to start over.
      </footer>
    </div>
  );
}
