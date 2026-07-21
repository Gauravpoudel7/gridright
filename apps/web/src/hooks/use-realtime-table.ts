"use client";

import { useEffect, useRef, useState } from "react";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

type ChangePayload<T> = {
  eventType: "INSERT" | "UPDATE" | "DELETE";
  new: T;
  old: Partial<T>;
};

/**
 * Subscribe to Supabase Realtime postgres_changes for a table.
 * Returns the latest change payload and whether the subscription is active.
 */
export function useRealtimeTable<T extends Record<string, unknown>>(
  table: string,
  filter?: string,
) {
  const [lastChange, setLastChange] = useState<ChangePayload<T> | null>(null);
  const [live, setLive] = useState(false);
  const channelRef = useRef<ReturnType<ReturnType<typeof getSupabaseBrowserClient>["channel"]> | null>(null);

  useEffect(() => {
    const supabase = getSupabaseBrowserClient();
    const channelName = `realtime:${table}:${filter ?? "all"}`;

    const channel = supabase.channel(channelName).on(
      // @ts-expect-error — overloaded signature; string form is valid
      "postgres_changes",
      {
        event: "*",
        schema: "public",
        table,
        ...(filter ? { filter } : {}),
      },
      (payload: ChangePayload<T>) => {
        setLastChange(payload);
      },
    );

    channel.subscribe((status) => {
      setLive(status === "SUBSCRIBED");
    });

    channelRef.current = channel;

    return () => {
      supabase.removeChannel(channel);
      setLive(false);
    };
  }, [table, filter]);

  return { lastChange, live };
}
