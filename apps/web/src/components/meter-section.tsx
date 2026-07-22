"use client";

import { useEffect, useMemo, useState } from "react";
import { useRealtimeTable } from "@/hooks/use-realtime-table";
import { LiveDot } from "@/components/realtime-dashboard";

export type MeterReading = {
  reading_at: string;
  generation_kwh: number;
  consumption_kwh: number;
  surplus_kwh: number;
  grid_export_kwh: number;
};

export type MeterDevice = { meter_device_id: string } | null;

function num(v: unknown): number {
  return typeof v === "number" ? v : parseFloat(String(v ?? 0)) || 0;
}

function Stat({ label, value, unit, accent }: { label: string; value: number; unit: string; accent?: boolean }) {
  return (
    <div>
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${accent ? "text-green-600 dark:text-green-400" : "text-zinc-900 dark:text-zinc-50"}`}>
        {value.toFixed(2)} <span className="text-xs font-normal text-zinc-500">{unit}</span>
      </p>
    </div>
  );
}

/** Rolling chart of recent readings (newest last). Inline SVG, no chart lib. */
function ReadingsChart({ readings }: { readings: MeterReading[] }) {
  const width = 560;
  const height = 56;
  const max = Math.max(0.1, ...readings.map((r) => num(r.generation_kwh)));
  const x = (i: number) => (i / Math.max(1, readings.length - 1)) * width;
  const y = (v: number) => height - (v / max) * (height - 4) - 2;
  const line = (pick: (r: MeterReading) => number) =>
    readings.map((r, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(pick(r)).toFixed(1)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-14 w-full" role="img" aria-label="Recent generation and surplus readings">
      <path d={line((r) => num(r.generation_kwh))} fill="none" className="stroke-amber-400" strokeWidth="1.5" />
      <path d={line((r) => num(r.surplus_kwh))} fill="none" className="stroke-green-500" strokeWidth="1.5" />
    </svg>
  );
}

export function MeterSection({
  sellerId,
  initialDevice,
  initialReadings,
}: {
  sellerId: string;
  initialDevice: MeterDevice;
  initialReadings: MeterReading[];
}) {
  // Device registration happens automatically when the seller binds their
  // meter with a pairing code (see MeterBindingSection) — this section only
  // displays the live readings that arrive once the meter starts pushing.
  const [device] = useState(initialDevice);
  // Keep oldest-first for charting; API returns newest-first.
  const [readings, setReadings] = useState<MeterReading[]>(() => [...initialReadings].reverse());

  const { lastChange, live } = useRealtimeTable<MeterReading & { seller_id: string }>(
    "meter_readings",
    `seller_id=eq.${sellerId}`,
  );

  useEffect(() => {
    if (!lastChange || lastChange.eventType !== "INSERT") return;
    setReadings((prev) => [...prev, lastChange.new].slice(-48));
  }, [lastChange]);

  const latest = readings[readings.length - 1];
  const exportedToday = useMemo(() => {
    const today = new Date().toDateString();
    return readings
      .filter((r) => new Date(r.reading_at).toDateString() === today)
      .reduce((sum, r) => sum + num(r.grid_export_kwh), 0);
  }, [readings]);

  // Empty state: no meter bound yet — binding (with a pairing code) is the
  // only way to connect a meter; there is no manual device registration.
  if (!device) {
    return (
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Smart meter</h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Live generation and surplus will appear here once your meter is bound
          (see Meter binding above) and starts sending readings.
        </p>
      </section>
    );
  }

  return (
    <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Smart meter</h2>
          <LiveDot live={live} />
        </div>
        <span className="font-mono text-xs text-zinc-500">{device.meter_device_id}</span>
      </div>

      {readings.length === 0 ? (
        <p className="text-sm text-zinc-500">
          Meter connected — waiting for the first reading.
        </p>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Generation" value={num(latest.generation_kwh)} unit="kWh" />
            <Stat label="Consumption" value={num(latest.consumption_kwh)} unit="kWh" />
            <Stat label="Surplus" value={num(latest.surplus_kwh)} unit="kWh" accent />
            <Stat label="Fed to grid today" value={exportedToday} unit="kWh" />
          </div>
          <ReadingsChart readings={readings} />
        </>
      )}
    </section>
  );
}
