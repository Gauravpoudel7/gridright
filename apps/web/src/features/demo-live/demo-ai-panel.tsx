// DEMO-ONLY — visual twin of the "AI recommendation" row that appears
// in the real operator feed. The real recommender (apps/api/app/services/
// recommender.py) calls Groq with a prompt and response_format=json_object,
// or falls back to a rules estimator. This panel shows the same fields
// a real operator would see: model name, prompt, raw JSON response, the
// fleet context that was passed in, and the policy check outcome.

import { DEMO_POLICY } from "./policy";
import type { AiTrace } from "./sim";

type DemoAiPanelProps = {
  trace: AiTrace | null;
  latestDirection: string | null;
  latestDecision: "auto-approved" | "needs_review" | null;
  latestKwh: number | null;
  latestPrice: number | null;
};

function fmtPrice(n: number) {
  return `$${n.toFixed(4)}`;
}

function DirectionBadge({ direction }: { direction: string }) {
  const styles =
    direction === "import"
      ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
      : direction === "export"
        ? "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400"
        : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400";
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles}`}
    >
      {direction.replace("_", " ")}
    </span>
  );
}

export function DemoAiPanel({
  trace,
  latestDirection,
  latestDecision,
  latestKwh,
  latestPrice,
}: DemoAiPanelProps) {
  return (
    <section className="mb-6 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            AI recommendation
          </h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Latest call from the recommender service. The operator policy
            layer (deterministic) checks the output before any money moves.
          </p>
        </div>
        <span className="inline-block rounded bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-400">
          model: {trace?.modelLabel ?? "—"}
        </span>
      </div>

      {/* Summary line — mirrors operator-feed-client.tsx: the first row
          of every feed item is "{kwh} kWh @ ${ai_price}/kWh" + status
          badge. We render the same shape here for the most recent call. */}
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-900 dark:text-zinc-50">
        {latestKwh != null && latestPrice != null ? (
          <span className="font-medium tabular-nums">
            {latestKwh.toFixed(2)} kWh @ {fmtPrice(latestPrice)}/kWh
          </span>
        ) : (
          <span className="text-zinc-500">Waiting for first reading…</span>
        )}
        {latestDirection && <DirectionBadge direction={latestDirection} />}
        {latestDecision && (
          <span
            className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
              latestDecision === "auto-approved"
                ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                : "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
            }`}
          >
            {latestDecision}
          </span>
        )}
        {trace && (
          <span className="text-xs text-zinc-500">
            · {trace.latencyMs}ms
          </span>
        )}
      </div>

      {/* Two-column "request / response" view — the same fields a real
          operator would see in the server logs. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Request
          </p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
            {trace?.prompt ?? "—"}
          </pre>
          {trace?.fleetContext && (
            <p className="mt-2 text-xs text-zinc-500">
              fleet.net_position_kwh:{" "}
              <span className="font-mono text-zinc-700 dark:text-zinc-300">
                {trace.fleetContext.netPositionKwh.toFixed(1)}
              </span>{" "}
              (passes into the price-nudge factor)
            </p>
          )}
        </div>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Response (raw JSON)
          </p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
            {trace?.rawResponse ?? "—"}
          </pre>
        </div>
      </div>

      {/* Policy check outcome — same band check the API runs in
          apps/api/app/services/policy_checker.py. */}
      <div className="mt-4 rounded border border-zinc-200 bg-zinc-50 p-3 text-xs text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
        <p className="font-medium text-zinc-900 dark:text-zinc-50">
          Policy layer (deterministic — band ±{DEMO_POLICY.bandWidthPercentage}%
          around the feed-in tariff, pool cap {DEMO_POLICY.poolCapacityLimitKwh}{" "}
          kWh)
        </p>
        <p className="mt-1">
          {latestDecision === "auto-approved"
            ? "✓ Price within band and absorption within pool cap. Auto-approved — no operator action required."
            : latestDecision === "needs_review"
              ? "⚠ Outside policy band — queued for operator review (auto-resolves after 5s in this demo)."
              : "Awaiting first reading."}
        </p>
      </div>
    </section>
  );
}
