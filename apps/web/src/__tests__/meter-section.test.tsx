import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import React from "react";

// Controllable mock for the realtime hook — tests push changes through it.
const realtimeState: { lastChange: unknown; live: boolean } = { lastChange: null, live: false };
vi.mock("@/hooks/use-realtime-table", () => ({
  useRealtimeTable: vi.fn(() => realtimeState),
}));

vi.mock("@/app/actions/meter", () => ({
  registerMeterDevice: vi.fn(),
}));

import { MeterSection, type MeterReading } from "@/components/meter-section";

const READING: MeterReading = {
  reading_at: "2026-07-20T12:00:00+00:00",
  generation_kwh: 4.2,
  consumption_kwh: 1.1,
  surplus_kwh: 3.1,
  grid_export_kwh: 1.2,
};

beforeEach(() => {
  realtimeState.lastChange = null;
  realtimeState.live = false;
});

afterEach(() => cleanup());

describe("MeterSection", () => {
  it("shows the connect-your-meter empty state when no device is registered", () => {
    render(<MeterSection sellerId="seller-1" initialDevice={null} initialReadings={[]} />);
    expect(screen.getByText(/Connect your smart meter/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register meter" })).toBeInTheDocument();
  });

  it("shows waiting state when device registered but zero readings", () => {
    render(
      <MeterSection
        sellerId="seller-1"
        initialDevice={{ meter_device_id: "METER-001" }}
        initialReadings={[]}
      />,
    );
    expect(screen.getByText(/waiting for the first reading/i)).toBeInTheDocument();
    expect(screen.getByText("METER-001")).toBeInTheDocument();
  });

  it("renders latest reading stats from initial data", () => {
    render(
      <MeterSection
        sellerId="seller-1"
        initialDevice={{ meter_device_id: "METER-001" }}
        initialReadings={[READING]}
      />,
    );
    expect(screen.getByText("Generation")).toBeInTheDocument();
    expect(screen.getByText("4.20")).toBeInTheDocument();
    expect(screen.getByText("3.10")).toBeInTheDocument(); // surplus
  });

  it("appends a new reading on a mocked realtime INSERT event", () => {
    const { rerender } = render(
      <MeterSection
        sellerId="seller-1"
        initialDevice={{ meter_device_id: "METER-001" }}
        initialReadings={[READING]}
      />,
    );

    realtimeState.lastChange = {
      eventType: "INSERT",
      new: {
        ...READING,
        reading_at: "2026-07-20T12:10:00+00:00",
        generation_kwh: 5.5,
        surplus_kwh: 4.4,
        seller_id: "seller-1",
      },
      old: {},
    };
    rerender(
      <MeterSection
        sellerId="seller-1"
        initialDevice={{ meter_device_id: "METER-001" }}
        initialReadings={[READING]}
      />,
    );

    // Latest stats now reflect the inserted reading
    expect(screen.getByText("5.50")).toBeInTheDocument();
    expect(screen.getByText("4.40")).toBeInTheDocument();
  });
});
