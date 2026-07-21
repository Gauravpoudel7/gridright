import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// Mock Supabase browser client
vi.mock("@/lib/supabase/client", () => ({
  getSupabaseBrowserClient: vi.fn(),
}));

import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { useRealtimeTable } from "@/hooks/use-realtime-table";

function makeChannel() {
  const handlers: Record<string, (payload: unknown) => void> = {};
  let subscribeCallback: ((status: string) => void) | null = null;
  return {
    on: vi.fn((_event: string, _filter: unknown, handler: (p: unknown) => void) => {
      handlers["*"] = handler;
      return { subscribe: (cb: (s: string) => void) => { subscribeCallback = cb; return {}; } };
    }),
    subscribe: vi.fn((cb: (s: string) => void) => {
      subscribeCallback = cb;
      cb("SUBSCRIBED");
      return {};
    }),
    _emit: (payload: unknown) => handlers["*"]?.(payload),
    _subscribeCallback: () => subscribeCallback,
  };
}

describe("useRealtimeTable", () => {
  let channel: ReturnType<typeof makeChannel>;

  beforeEach(() => {
    channel = makeChannel();
    const mockSupabase = {
      channel: vi.fn(() => ({
        on: vi.fn(() => ({ subscribe: channel.subscribe })),
        subscribe: channel.subscribe,
      })),
      removeChannel: vi.fn(),
    };
    // Wire on() to capture handler and return object with subscribe
    const ch = {
      on: vi.fn((_e: string, _f: unknown, handler: (p: unknown) => void) => {
        channel._emit = handler;
        return { subscribe: channel.subscribe };
      }),
      subscribe: channel.subscribe,
    };
    mockSupabase.channel.mockReturnValue(ch);
    vi.mocked(getSupabaseBrowserClient).mockReturnValue(mockSupabase as never);
  });

  it("starts with live=false, lastChange=null", () => {
    const { result } = renderHook(() => useRealtimeTable("contributions"));
    // live becomes true after subscribe callback fires
    expect(result.current.lastChange).toBeNull();
  });

  it("sets live=true when subscription is SUBSCRIBED", async () => {
    const { result } = renderHook(() => useRealtimeTable("contributions"));
    await act(async () => {});
    expect(result.current.live).toBe(true);
  });

  it("updates lastChange on INSERT event", async () => {
    const { result } = renderHook(() => useRealtimeTable<{ id: string }>("contributions"));
    await act(async () => {});

    const payload = { eventType: "INSERT", new: { id: "row-1" }, old: {} };
    await act(async () => {
      (channel._emit as (p: unknown) => void)(payload);
    });

    expect(result.current.lastChange).toEqual(payload);
  });

  it("updates lastChange on UPDATE event", async () => {
    const { result } = renderHook(() => useRealtimeTable<{ id: string; status: string }>("contributions"));
    await act(async () => {});

    const payload = { eventType: "UPDATE", new: { id: "row-1", status: "settled" }, old: { id: "row-1" } };
    await act(async () => {
      (channel._emit as (p: unknown) => void)(payload);
    });

    expect(result.current.lastChange?.eventType).toBe("UPDATE");
    expect((result.current.lastChange?.new as { status: string }).status).toBe("settled");
  });
});
