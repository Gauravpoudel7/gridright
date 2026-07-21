// DEMO-ONLY: safe to delete — remove this file along with src/features/demo/, src/app/demo/, and the "Try the Demo" button on src/app/page.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import {
  sampleMeter,
  tickKwh,
  DEMO_TICK_INTERVAL_MS,
  DEMO_MINUTES_PER_TICK,
  DEMO_HISTORY_LENGTH,
  type MeterSample,
} from "./meter-sim";

// Start the simulated day at 09:00 so generation is already visible on load.
const DEMO_START_MINUTE = 9 * 60;

export type DemoMeterState = {
  current: MeterSample;
  history: MeterSample[];
  /** Running total of simulated kWh exported to the grid "today". */
  exportedTodayKwh: number;
  /** Surplus accumulated since the last submission — what the seller can
   *  list to the pool right now. Consumed (zeroed) on submit. */
  availableSurplusKwh: number;
  running: boolean;
};

export type DemoMeter = DemoMeterState & {
  toggle: () => void;
  reset: () => void;
  /** Return the currently-available surplus and zero the accumulator. */
  consumeAvailableSurplus: () => number;
};

function initialState(): DemoMeterState {
  const first = sampleMeter(DEMO_START_MINUTE);
  return {
    current: first,
    history: [first],
    exportedTodayKwh: 0,
    availableSurplusKwh: 0,
    running: true,
  };
}

export function useDemoMeter(): DemoMeter {
  const [state, setState] = useState<DemoMeterState>(initialState);
  const minuteRef = useRef(DEMO_START_MINUTE);
  // Mirror of availableSurplusKwh so consume can read it synchronously.
  const availableRef = useRef(0);

  useEffect(() => {
    if (!state.running) return;
    const interval = setInterval(() => {
      minuteRef.current += DEMO_MINUTES_PER_TICK;
      const sample = sampleMeter(minuteRef.current);
      availableRef.current = Math.round((availableRef.current + tickKwh(sample.surplusKw)) * 100) / 100;
      setState((prev) => ({
        ...prev,
        current: sample,
        history: [...prev.history, sample].slice(-DEMO_HISTORY_LENGTH),
        exportedTodayKwh: Math.round((prev.exportedTodayKwh + tickKwh(sample.gridExportKw)) * 100) / 100,
        availableSurplusKwh: availableRef.current,
      }));
    }, DEMO_TICK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [state.running]);

  const toggle = () => setState((prev) => ({ ...prev, running: !prev.running }));

  const reset = () => {
    minuteRef.current = DEMO_START_MINUTE;
    availableRef.current = 0;
    setState(initialState());
  };

  const consumeAvailableSurplus = () => {
    const amount = availableRef.current;
    availableRef.current = 0;
    setState((prev) => ({ ...prev, availableSurplusKwh: 0 }));
    return amount;
  };

  return { ...state, toggle, reset, consumeAvailableSurplus };
}
