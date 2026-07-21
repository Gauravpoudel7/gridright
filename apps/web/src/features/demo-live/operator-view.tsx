// DEMO-ONLY — Operator dashboard lookalike. Mirrors the real page
// (src/app/operator/dashboard/page.tsx) section by section, in the same
// order: header stat cards (spread / uplift / settled energy / payouts),
// the real <FleetOutlook /> component fed with synthetic forecast data,
// the AI recommendation panel (demo extra), the exception queue with the
// same yellow review cards and Approve/Adjust/Reject buttons, the
// import/export panel with pool stats, the distribution-by-seller table,
// and finally the wallet row + recommendation feed from
// operator-feed-client.tsx. Approve is clickable and settles the
// exception through the same resolve path the auto-resolver uses;
// Adjust/Reject are rendered but disabled in the demo.

import { FleetOutlook } from "@/app/operator/dashboard/fleet-outlook";
import { DemoAiPanel } from "./demo-ai-panel";
import { DemoWallet } from "./demo-wallet";
import { FEED_IN_TARIFF, POLICY_OPERATOR_MARGIN_PCT } from "./policy";
import {
  buildFleetOutlook,
  type AiTrace,
  type Contribution,
  type Exception,
} from "./sim";

function fmt(n: number, d = 2): string {
  return n.toFixed(d);
}
function fmtPrice(n: number): string {
  return `$${n.toFixed(4)}`;
}

function statusBadge(status: string) {
  const styles =
    status === "settled"
      ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
      : status === "exception_queued" || status === "exception_resolving"
        ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
        : "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles}`}>
      {status.replace("_", " ")}
    </span>
  );
}

/** Same direction badge as the real operator dashboard page. */
function directionBadge(direction: string) {
  const styles =
    direction === "import"
      ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
      : direction === "export"
        ? "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400"
        : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400";
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles}`}>{direction.replace("_", " ")}</span>;
}

function StatCard({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
        {value}
        <span className="ml-1 text-sm font-normal text-zinc-500">{unit}</span>
      </p>
    </div>
  );
}

/** Visual twin of the LiveDot in components/realtime-dashboard.tsx. */
function LivePill({ label = "Live" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
      </span>
      {label}
    </span>
  );
}

/** Exception card — same markup as the real exception queue on
 *  src/app/operator/dashboard/page.tsx, with the ReviewControls buttons.
 *  Approve works (settles via the demo resolve path); Adjust and Reject
 *  are rendered but disabled so the card still reads like the real one. */
function ExceptionCard({
  exception,
  onApprove,
}: {
  exception: Exception;
  onApprove: (id: string) => void;
}) {
  return (
    <li className="rounded-lg border border-yellow-300 bg-yellow-50 p-4 dark:border-yellow-900/50 dark:bg-yellow-900/10">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-zinc-900 dark:text-zinc-50">
        <span className="font-medium">
          {fmt(exception.kwh)} kWh @ {fmtPrice(exception.recommendedPrice)}/kWh
        </span>
        {directionBadge(exception.direction)}
      </div>
      <p className="mb-3 text-sm text-yellow-800 dark:text-yellow-400">{exception.deviationReason}</p>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onApprove(exception.id)}
          className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
        >
          Approve
        </button>
        <button
          type="button"
          disabled
          title="Disabled in the demo"
          className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white opacity-50"
        >
          Adjust
        </button>
        <button
          type="button"
          disabled
          title="Disabled in the demo"
          className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white opacity-50"
        >
          Reject
        </button>
        <span className="ml-1 text-xs italic text-yellow-700 dark:text-yellow-500">
          approve now — or it auto-resolves in ~8s
        </span>
      </div>
    </li>
  );
}

function FeedItem({ item }: { item: Contribution }) {
  return (
    <li className="border-b border-zinc-100 pb-3 last:border-0 last:pb-0 dark:border-zinc-800/50">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-900 dark:text-zinc-50">
        <span className="font-medium">
          {fmt(item.kwh)} kWh @ {fmtPrice(item.finalPrice)}/kWh
        </span>
        {statusBadge(item.status)}
        {item.approvalType && (
          <span className="text-xs text-zinc-500">
            {item.approvalType === "auto" ? "auto-approved" : "human decision"}
          </span>
        )}
        <span className="text-xs text-zinc-500">· {item.direction.replace("_", " ")}</span>
      </div>
      {item.approvalReason && (
        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
          Reason: {item.approvalReason}
        </p>
      )}
      {item.txSignature && (
        <p className="mt-1 break-all font-mono text-[11px] text-zinc-500">
          tx: {item.txSignature.slice(0, 24)}…{item.txSignature.slice(-8)}
        </p>
      )}
      <p className="mt-1 text-xs text-zinc-500">
        {new Date(item.createdAt).toLocaleString()}
      </p>
    </li>
  );
}

export function OperatorView({
  contributions,
  exceptions,
  cumulativeKwh,
  totalEarnedUsd,
  pool,
  simulatedMinute,
  latestAiTrace,
  onApproveException,
}: {
  contributions: Contribution[];
  exceptions: Exception[];
  cumulativeKwh: number;
  totalEarnedUsd: number;
  pool: { currentAbsorptionKwh: number; absorptionLimitKwh: number };
  simulatedMinute: number;
  latestAiTrace: AiTrace | null;
  onApproveException: (id: string) => void;
}) {
  const settled = contributions.filter((c) => c.status === "settled");

  // Same four headline figures as the real operator dashboard's stats API.
  const totalPayouts = totalEarnedUsd;
  const spreadCaptured = totalEarnedUsd * (POLICY_OPERATOR_MARGIN_PCT / 100);
  const avgUplift =
    settled.length === 0
      ? 0
      : settled.reduce(
          (s, c) => s + ((c.finalPrice - FEED_IN_TARIFF) / FEED_IN_TARIFF) * 100,
          0,
        ) / settled.length;

  // Pricing exceptions vs import/export ones — same split as the real page.
  const pricingExceptions = exceptions.filter((e) => e.direction === "local_pool");
  const importExportExceptions = exceptions.filter((e) => e.direction !== "local_pool");

  const fleet = buildFleetOutlook(simulatedMinute);

  // The "latest" contribution drives the AI panel's summary line.
  const latest = contributions[0] ?? null;

  // Distribution by seller — the demo seller's real (simulated) totals,
  // plus two community peers so the table looks like the real fleet.
  const distribution = [
    { seller_id: "demo-seller-001 (you)", total_kwh: cumulativeKwh, contribution_count: settled.length },
    { seller_id: "community-seller-014", total_kwh: cumulativeKwh * 0.62, contribution_count: Math.ceil(settled.length * 0.7) },
    { seller_id: "community-seller-032", total_kwh: cumulativeKwh * 0.38, contribution_count: Math.ceil(settled.length * 0.4) },
  ];

  return (
    <div>
      {/* Headline stats — same four cards as the real operator dashboard. */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total spread captured" value={`$${fmt(spreadCaptured)}`} unit="" />
        <StatCard label="Avg seller uplift over tariff" value={fmt(avgUplift)} unit="%" />
        <StatCard label="Settled energy" value={fmt(cumulativeKwh)} unit="kWh" />
        <StatCard label="Total payouts" value={`$${fmt(totalPayouts)}`} unit="" />
      </div>

      {/* Fleet outlook — the real Phase-4 component, fed with a synthetic
          24h forecast anchored at the simulated clock. */}
      <FleetOutlook data={fleet} />

      {/* AI recommendation panel — demo extra: model, prompt, raw JSON,
          fleet context, and the policy verdict the real recommender logs. */}
      <DemoAiPanel
        trace={latestAiTrace}
        latestDirection={latest?.direction ?? null}
        latestDecision={latest?.decision ?? null}
        latestKwh={latest?.kwh ?? null}
        latestPrice={latest?.recommendedPrice ?? null}
      />

      {/* Exception queue — same section header, copy, and yellow review
          cards as the real page. */}
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-1 flex items-center gap-2">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Exception queue</h2>
          {pricingExceptions.length > 0 && (
            <span className="inline-block rounded bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400">
              {pricingExceptions.length} pending
            </span>
          )}
        </div>
        <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">Recommendations outside the policy band.</p>
        {pricingExceptions.length === 0 ? (
          <p className="text-sm text-zinc-500">No pending exceptions.</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {pricingExceptions.map((ex) => (
              <ExceptionCard key={ex.id} exception={ex} onApprove={onApproveException} />
            ))}
          </ul>
        )}
      </section>

      {/* Import/export panel — same pool stat cards and blue review cards
          as the real page. */}
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Import / export</h2>
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard label="Pool contributed" value={fmt(cumulativeKwh)} unit="kWh" />
          <StatCard label="Current absorption" value={fmt(pool.currentAbsorptionKwh)} unit="kWh" />
          <StatCard label="Absorption limit" value={fmt(pool.absorptionLimitKwh)} unit="kWh" />
        </div>
        {importExportExceptions.length === 0 ? (
          <p className="text-sm text-zinc-500">No pending import or export recommendations.</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {importExportExceptions.map((ex) => (
              <li key={ex.id} className="rounded-lg border border-blue-300 bg-blue-50 p-4 dark:border-blue-900/50 dark:bg-blue-900/10">
                <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                  {directionBadge(ex.direction)}
                  <span className="font-medium">
                    {fmt(ex.kwh)} kWh @ {fmtPrice(ex.recommendedPrice)}/kWh
                  </span>
                </div>
                <p className="mb-3 text-sm text-blue-800 dark:text-blue-400">{ex.deviationReason}</p>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onApproveException(ex.id)}
                    className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
                  >
                    Approve
                  </button>
                  <span className="text-xs italic text-blue-700 dark:text-blue-400">
                    approve now — or it auto-resolves in ~8s
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Distribution by seller — same table as the real page; the two
          community rows are simulated peers scaled off the live totals. */}
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Distribution by seller</h2>
        <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">Community peers are simulated.</p>
        {cumulativeKwh === 0 ? (
          <p className="text-sm text-zinc-500">No contributions yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
                <th className="pb-2 pr-4 font-medium">Seller</th>
                <th className="pb-2 pr-4 font-medium">Total kWh</th>
                <th className="pb-2 font-medium">Contributions</th>
              </tr>
            </thead>
            <tbody>
              {distribution.map((item) => (
                <tr key={item.seller_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/50">
                  <td className="py-2 pr-4 font-mono text-xs">{item.seller_id}</td>
                  <td className="py-2 pr-4">{fmt(item.total_kwh)}</td>
                  <td className="py-2">{item.contribution_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Operator wallet card — sits directly above the feed, same as the
          real page's OperatorFeedClient layout. */}
      <DemoWallet role="operator" prompt="Connect Operator Wallet" />

      {/* Recommendation feed — same list markup as operator-feed-client.tsx */}
      <section className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-4 flex items-center gap-2">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Recommendation feed</h2>
          <LivePill />
        </div>
        {contributions.length === 0 ? (
          <p className="text-sm text-zinc-500">No recommendations yet — meter just started.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {contributions.map((c) => (
              <FeedItem key={c.id} item={c} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
