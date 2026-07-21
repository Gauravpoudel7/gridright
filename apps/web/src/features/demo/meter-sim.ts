// DEMO-ONLY: safe to delete — remove this file along with src/features/demo/, src/app/demo/, and the "Try the Demo" button on src/app/page.tsx
//
// In-memory smart-meter simulator for the /demo walkthrough. Produces fake
// generation/consumption/surplus/grid-export figures on a daylight-shaped
// curve. Purely illustrative — no backend, no DB, no relation to the real
// meter ingestion path.

// PLACEHOLDER demo curve parameters — illustrative only, not real hardware specs.
export const DEMO_PEAK_GENERATION_KW = 5.2; // rooftop array peak output at solar noon
export const DEMO_BASE_CONSUMPTION_KW = 0.4; // overnight household baseline
export const DEMO_PEAK_CONSUMPTION_KW = 1.6; // morning/evening usage peaks
export const DEMO_SUNRISE_MINUTE = 6 * 60; // 06:00
export const DEMO_SUNSET_MINUTE = 19 * 60; // 19:00
export const DEMO_TICK_INTERVAL_MS = 1_000; // one real second per tick
export const DEMO_MINUTES_PER_TICK = 10; // each tick advances the simulated clock this much
export const DEMO_HISTORY_LENGTH = 48; // sparkline window (48 ticks = 8 simulated hours)

export type MeterSample = {
  /** Simulated minute-of-day this sample was taken at (0–1439). */
  minuteOfDay: number;
  generationKw: number;
  consumptionKw: number;
  /** Generation minus consumption, floored at 0. */
  surplusKw: number;
  /** Portion of surplus exported to the grid (what the pool can't absorb locally). */
  gridExportKw: number;
};

const MINUTES_PER_DAY = 24 * 60;

/**
 * Sample the simulated meter at a given minute of the (simulated) day.
 * `rand` is injectable so tests can pin jitter to a known value; it should
 * return values in [0, 1) like Math.random.
 */
export function sampleMeter(minuteOfDay: number, rand: () => number = Math.random): MeterSample {
  const minute = ((minuteOfDay % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;

  // Daylight-shaped generation: half-sine between sunrise and sunset, zero at night.
  let generationKw = 0;
  if (minute > DEMO_SUNRISE_MINUTE && minute < DEMO_SUNSET_MINUTE) {
    const dayFraction = (minute - DEMO_SUNRISE_MINUTE) / (DEMO_SUNSET_MINUTE - DEMO_SUNRISE_MINUTE);
    const cloudJitter = 0.85 + rand() * 0.15; // light "passing cloud" noise
    generationKw = DEMO_PEAK_GENERATION_KW * Math.sin(Math.PI * dayFraction) * cloudJitter;
  }

  // Consumption: baseline plus morning (~07:30) and evening (~19:30) bumps.
  const morningBump = gaussianBump(minute, 7.5 * 60, 90);
  const eveningBump = gaussianBump(minute, 19.5 * 60, 120);
  const usageJitter = 0.9 + rand() * 0.2;
  const consumptionKw =
    (DEMO_BASE_CONSUMPTION_KW +
      (DEMO_PEAK_CONSUMPTION_KW - DEMO_BASE_CONSUMPTION_KW) * Math.max(morningBump, eveningBump)) *
    usageJitter;

  const surplusKw = Math.max(0, generationKw - consumptionKw);
  // Demo fiction: the local pool absorbs up to 60% of surplus; the rest exports.
  const gridExportKw = surplusKw * 0.4;

  return {
    minuteOfDay: minute,
    generationKw: round2(generationKw),
    consumptionKw: round2(consumptionKw),
    surplusKw: round2(surplusKw),
    gridExportKw: round2(gridExportKw),
  };
}

/** Unnormalized bell curve centered at `centerMinute` with the given width. */
function gaussianBump(minute: number, centerMinute: number, widthMinutes: number): number {
  const d = minute - centerMinute;
  return Math.exp(-(d * d) / (2 * widthMinutes * widthMinutes));
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** kWh contribution of one tick: kW held for DEMO_MINUTES_PER_TICK simulated minutes. */
export function tickKwh(kw: number): number {
  return round2((kw * DEMO_MINUTES_PER_TICK) / 60);
}
