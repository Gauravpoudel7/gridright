// DEMO-ONLY — Seller dashboard lookalike. Mirrors the real page section
// by section, in the same order: Smart meter card (with the 4-stat grid
// and readings chart from src/components/meter-section.tsx), Phantom
// wallet row, the stat-card grid, and the contribution-history table
// from src/app/dashboard/seller-dashboard-client.tsx — all fed by
// simulated data from useLiveDemo. No real wallet, no real Supabase,
// no real Solana. Export CSV downloads the in-memory contributions.

import { DemoWallet } from "./demo-wallet";
import { DEMO_METER_DEVICE_ID, type Contribution, type MeterReading } from "./sim";

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
        : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400";
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles}`}
    >
      {status.replace("_", " ")}
    </span>
  );
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

/** Visual twin of the LiveDot in components/realtime-dashboard.tsx —
 *  re-implemented locally so the demo bundle never touches the realtime
 *  Supabase hooks. */
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

/** Twin of the Stat cells inside components/meter-section.tsx. */
function MeterStat({ label, value, unit, accent }: { label: string; value: number; unit: string; accent?: boolean }) {
  return (
    <div>
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${accent ? "text-green-600 dark:text-green-400" : "text-zinc-900 dark:text-zinc-50"}`}>
        {value.toFixed(2)} <span className="text-xs font-normal text-zinc-500">{unit}</span>
      </p>
    </div>
  );
}

/** Rolling chart of recent readings (oldest first) — same inline-SVG
 *  approach and colors as the real meter card: amber = generation,
 *  green = surplus. */
function ReadingsChart({ readings }: { readings: MeterReading[] }) {
  const width = 560;
  const height = 56;
  const max = Math.max(0.1, ...readings.map((r) => r.generationKwh));
  const x = (i: number) => (i / Math.max(1, readings.length - 1)) * width;
  const y = (v: number) => height - (v / max) * (height - 4) - 2;
  const line = (pick: (r: MeterReading) => number) =>
    readings.map((r, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(pick(r)).toFixed(1)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-14 w-full" role="img" aria-label="Recent simulated generation and surplus readings">
      <path d={line((r) => r.generationKwh)} fill="none" className="stroke-amber-400" strokeWidth="1.5" />
      <path d={line((r) => r.kwh)} fill="none" className="stroke-green-500" strokeWidth="1.5" />
    </svg>
  );
}

function minuteToTime(minute: number): string {
  const h = Math.floor(minute / 60) % 24;
  const m = minute % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** Client-side CSV of the in-memory contributions — the demo stand-in for
 *  the real dashboard's /history/export endpoint. */
function exportCsv(contributions: Contribution[]) {
  const header = "time,kwh,final_price_usd_per_kwh,earned_usd,status";
  const rows = contributions.map((c) =>
    [minuteToTime(c.minuteOfDay), c.kwh, c.finalPrice, c.payoutUsd, c.status].join(","),
  );
  const blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "gridright-demo-contributions.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function SellerView({
  contributions,
  cumulativeKwh,
  totalEarnedUsd,
  meterReadings,
  gridExportTodayKwh,
  simulatedMinute,
  running,
}: {
  contributions: Contribution[];
  cumulativeKwh: number;
  totalEarnedUsd: number;
  /** Newest-first, as stored in LiveDemoState. */
  meterReadings: MeterReading[];
  gridExportTodayKwh: number;
  simulatedMinute: number;
  running: boolean;
}) {
  // "Surplus this period" — unsettled + settled kWh since page load.
  const surplusThisPeriod = contributions.reduce((s, c) => s + c.kwh, 0);
  const latest = meterReadings[0] ?? null;
  const oldestFirst = [...meterReadings].reverse();

  return (
    <div>
      {/* Smart meter — twin of components/meter-section.tsx: header with
          live dot + mono device id, the 4-stat grid, and the readings
          chart, driven by the simulated meter. */}
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Smart meter</h2>
            {running && <LivePill />}
          </div>
          <span className="font-mono text-xs text-zinc-500">{DEMO_METER_DEVICE_ID}</span>
        </div>

        {!latest ? (
          <p className="text-sm text-zinc-500">Meter registered — waiting for the first reading.</p>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <MeterStat label="Generation" value={latest.generationKwh} unit="kWh" />
              <MeterStat label="Consumption" value={latest.consumptionKwh} unit="kWh" />
              <MeterStat label="Surplus" value={latest.kwh} unit="kWh" accent />
              <MeterStat label="Fed to grid today" value={gridExportTodayKwh} unit="kWh" />
            </div>
            <ReadingsChart readings={oldestFirst} />
            <p className="mt-1 text-xs text-zinc-500">
              Simulated clock {minuteToTime(simulatedMinute)} · one reading every 4s (≈10 simulated minutes)
            </p>
          </>
        )}
      </section>

      {/* Wallet card — mirrors the "Phantom wallet" row on the real seller
          dashboard. Visual twin of WalletConnect. */}
      <DemoWallet role="seller" prompt="Select Wallet" />

      {/* Stats — same grid + stat-card markup as the real seller dashboard. */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Surplus this period" value={fmt(surplusThisPeriod)} unit="kWh" />
        <StatCard label="Cumulative contributed" value={fmt(cumulativeKwh)} unit="kWh" />
        <StatCard label="Total earned" value={`$${fmt(totalEarnedUsd)}`} unit="USD" />
      </div>

      {/* History — same table layout, same status-badge vocabulary.
          The seller sees their own contribution table only — no
          recommendation feed (operator-only). */}
      <section className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Contribution history</h2>
            {running && <LivePill />}
          </div>
        </div>
        {contributions.length === 0 ? (
          <p className="text-sm text-zinc-500">No contributions yet — meter just started.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="pb-2 pr-4 font-medium">Time</th>
                  <th className="pb-2 pr-4 font-medium">kWh</th>
                  <th className="pb-2 pr-4 font-medium">Final price</th>
                  <th className="pb-2 pr-4 font-medium">Earned</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {contributions.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/50"
                  >
                    <td className="py-2 pr-4 text-zinc-900 dark:text-zinc-50">
                      {minuteToTime(c.minuteOfDay)}
                    </td>
                    <td className="py-2 pr-4 text-zinc-900 dark:text-zinc-50">{fmt(c.kwh)}</td>
                    <td className="py-2 pr-4 text-zinc-900 dark:text-zinc-50">
                      {fmtPrice(c.finalPrice)}/kWh
                    </td>
                    <td className="py-2 pr-4 text-zinc-900 dark:text-zinc-50">
                      {c.status === "settled" ? `$${fmt(c.payoutUsd)}` : "—"}
                    </td>
                    <td className="py-2">{statusBadge(c.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Export CSV — same placement as the real dashboard's export link. */}
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => exportCsv(contributions)}
          disabled={contributions.length === 0}
          className="rounded border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          Export CSV
        </button>
      </div>
    </div>
  );
}
