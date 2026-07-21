// DEMO-ONLY: safe to delete — remove this file along with src/features/demo/, src/app/demo/, and the "Try the Demo" button on src/app/page.tsx
"use client";

import { useDemoMeter, type DemoMeter } from "./use-demo-meter";
import { DEMO_HISTORY_LENGTH, type MeterSample } from "./meter-sim";

function minuteToClock(minute: number): string {
  const h = Math.floor(minute / 60) % 24;
  const m = minute % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div>
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p
        className={`text-lg font-semibold tabular-nums ${
          accent ? "text-green-600 dark:text-green-400" : "text-zinc-900 dark:text-zinc-50"
        }`}
      >
        {value.toFixed(2)} <span className="text-xs font-normal text-zinc-500">kW</span>
      </p>
    </div>
  );
}

/** Tiny inline sparkline of the recent generation + surplus history. No chart lib. */
function Sparkline({ history }: { history: MeterSample[] }) {
  const width = 280;
  const height = 48;
  const max = Math.max(0.1, ...history.map((s) => s.generationKw));
  const x = (i: number) => (i / Math.max(1, DEMO_HISTORY_LENGTH - 1)) * width;
  const y = (v: number) => height - (v / max) * (height - 4) - 2;
  const line = (pick: (s: MeterSample) => number) =>
    history.map((s, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(pick(s)).toFixed(1)}`).join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-12 w-full"
      role="img"
      aria-label="Generation and surplus over the simulated day"
    >
      <path d={line((s) => s.generationKw)} fill="none" className="stroke-amber-400" strokeWidth="1.5" />
      <path d={line((s) => s.surplusKw)} fill="none" className="stroke-green-500" strokeWidth="1.5" />
    </svg>
  );
}

/** Presentational meter tile — renders a meter instance owned elsewhere, so
 *  the scenario and the tile can share one live meter. */
export function MeterTileView({ meter }: { meter: DemoMeter }) {
  const { current, history, exportedTodayKwh, availableSurplusKwh, running, toggle } = meter;

  return (
    <div
      data-testid="demo-meter-tile"
      className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Smart meter (simulated)</p>
          <span
            className={`inline-block h-2 w-2 rounded-full ${running ? "animate-pulse bg-green-500" : "bg-zinc-400"}`}
          />
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs tabular-nums text-zinc-500" data-testid="demo-meter-clock">
            {minuteToClock(current.minuteOfDay)}
          </span>
          <button
            onClick={toggle}
            className="rounded border border-zinc-300 px-2 py-0.5 text-xs text-zinc-600 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-400"
          >
            {running ? "Pause" : "Resume"}
          </button>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-4 gap-3">
        <Stat label="Generation" value={current.generationKw} />
        <Stat label="Consumption" value={current.consumptionKw} />
        <Stat label="Surplus" value={current.surplusKw} accent />
        <Stat label="Grid export" value={current.gridExportKw} />
      </div>

      <Sparkline history={history} />

      <div className="mt-2 flex items-center justify-between text-xs text-zinc-500">
        <span>
          <span className="mr-3 inline-flex items-center gap-1">
            <span className="inline-block h-1.5 w-3 rounded bg-amber-400" /> generation
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-1.5 w-3 rounded bg-green-500" /> surplus
          </span>
        </span>
        <span className="tabular-nums" data-testid="demo-meter-available">
          Surplus available: {availableSurplusKwh.toFixed(2)} kWh
        </span>
      </div>
      <div className="mt-1 text-right text-xs text-zinc-400 tabular-nums" data-testid="demo-meter-exported">
        Fed to grid today: {exportedTodayKwh.toFixed(2)} kWh
      </div>
    </div>
  );
}

/** Self-contained tile that owns its own meter instance. Used where no shared
 *  meter is needed (and by the Phase 1 standalone test). */
export function DemoMeterTile() {
  const meter = useDemoMeter();
  return <MeterTileView meter={meter} />;
}
