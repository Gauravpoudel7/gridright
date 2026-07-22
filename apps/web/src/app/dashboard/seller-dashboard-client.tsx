"use client";

import { useRealtimeHistory, LiveDot } from "@/components/realtime-dashboard";

type HistoryItem = {
  id: string;
  period_start: string;
  period_end: string;
  kwh_contributed: number;
  amount_earned: number;
  status: string;
  tx_signature?: string;
};

type DashboardData = {
  surplus_this_period: number;
  cumulative_kwh: number;
  total_earned: number;
  period_start: string;
  period_end: string;
};

function fmt(v: number) { return v.toFixed(2); }

function statCard(label: string, value: string, unit: string) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
        {value}<span className="ml-1 text-sm font-normal text-zinc-500">{unit}</span>
      </p>
    </div>
  );
}

// Wallet connection lives in WalletActivate (payout wallet with signed-
// challenge ownership proof) — this component only renders stats + history.
export function SellerDashboardClient({
  initialDashboard,
  initialHistory,
}: {
  initialDashboard: DashboardData;
  initialHistory: HistoryItem[];
}) {
  const { history, live } = useRealtimeHistory(initialHistory);

  return (
    <div>
      {/* Stats */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {statCard("Surplus this period", fmt(initialDashboard.surplus_this_period), "kWh")}
        {statCard("Cumulative contributed", fmt(initialDashboard.cumulative_kwh), "kWh")}
        {statCard("Total earned", fmt(initialDashboard.total_earned), "USD")}
      </div>

      {/* History */}
      <section className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Contribution history</h2>
            <LiveDot live={live} />
          </div>
        </div>
        {history.length === 0 ? (
          <p className="text-sm text-zinc-500">No contributions yet.</p>
        ) : (
          <div className="max-h-72 overflow-y-auto overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="pb-2 pr-4 font-medium">Period start</th>
                  <th className="pb-2 pr-4 font-medium">Period end</th>
                  <th className="pb-2 pr-4 font-medium">kWh</th>
                  <th className="pb-2 pr-4 font-medium">Earned</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {history.map((item, i) => (
                  <tr key={item.id ?? i} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/50">
                    <td className="py-2 pr-4 text-zinc-900 dark:text-zinc-50">{new Date(item.period_start).toLocaleDateString()}</td>
                    <td className="py-2 pr-4 text-zinc-900 dark:text-zinc-50">{new Date(item.period_end).toLocaleDateString()}</td>
                    <td className="py-2 pr-4 text-zinc-900 dark:text-zinc-50">{fmt(item.kwh_contributed)}</td>
                    <td className="py-2 pr-4 text-zinc-900 dark:text-zinc-50">
                      {item.status === "settled" ? `$${fmt(item.amount_earned)}` : "—"}
                    </td>
                    <td className="py-2">
                      <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                        item.status === "settled" ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                        : item.status === "needs_review" ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
                        : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400"
                      }`}>
                        {item.status.replace("_", " ")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
