// DEMO-ONLY test: safe to delete along with src/features/demo/
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";
import React from "react";
import { DemoMeterTile } from "@/features/demo/demo-meter-tile";
import {
  sampleMeter,
  tickKwh,
  DEMO_TICK_INTERVAL_MS,
  DEMO_MINUTES_PER_TICK,
  DEMO_SUNRISE_MINUTE,
} from "@/features/demo/meter-sim";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("meter-sim", () => {
  it("generates zero at night and positive output mid-day", () => {
    const rand = () => 0.5; // pin jitter
    const night = sampleMeter(2 * 60, rand); // 02:00
    const noon = sampleMeter(12.5 * 60, rand); // 12:30 (solar noon for 06–19 window)
    expect(night.generationKw).toBe(0);
    expect(noon.generationKw).toBeGreaterThan(3);
    expect(noon.surplusKw).toBeGreaterThan(0);
    // grid export is a fraction of surplus, never more than it
    expect(noon.gridExportKw).toBeLessThanOrEqual(noon.surplusKw);
  });

  it("floors surplus at 0 when consumption exceeds generation", () => {
    const rand = () => 0.5;
    // Just after sunrise: tiny generation, evening/morning consumption baseline still applies
    const s = sampleMeter(DEMO_SUNRISE_MINUTE + 5, rand);
    expect(s.surplusKw).toBeGreaterThanOrEqual(0);
    // At night surplus must be exactly 0
    expect(sampleMeter(0, rand).surplusKw).toBe(0);
  });

  it("tickKwh converts kW held for one tick into kWh", () => {
    expect(tickKwh(6)).toBe((6 * DEMO_MINUTES_PER_TICK) / 60);
  });
});

describe("DemoMeterTile", () => {
  it("renders and advances the simulated clock on timer tick (mocked timers)", () => {
    vi.useFakeTimers();
    render(<DemoMeterTile />);

    expect(screen.getByTestId("demo-meter-tile")).toBeInTheDocument();
    const clockBefore = screen.getByTestId("demo-meter-clock").textContent;

    act(() => {
      vi.advanceTimersByTime(DEMO_TICK_INTERVAL_MS * 3);
    });

    const clockAfter = screen.getByTestId("demo-meter-clock").textContent;
    expect(clockAfter).not.toBe(clockBefore);
    // "Fed to grid today" line is present and numeric
    expect(screen.getByTestId("demo-meter-exported").textContent).toMatch(/\d+\.\d{2} kWh/);
  });

  it("stops ticking when paused", () => {
    vi.useFakeTimers();
    render(<DemoMeterTile />);

    act(() => {
      screen.getByRole("button", { name: "Pause" }).click();
    });
    const clockBefore = screen.getByTestId("demo-meter-clock").textContent;

    act(() => {
      vi.advanceTimersByTime(DEMO_TICK_INTERVAL_MS * 3);
    });

    expect(screen.getByTestId("demo-meter-clock").textContent).toBe(clockBefore);
  });
});
