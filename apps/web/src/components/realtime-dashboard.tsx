"use client";

import { useEffect, useState } from "react";
import { useRealtimeTable } from "@/hooks/use-realtime-table";

type HistoryItem = {
  id: string;
  period_start: string;
  period_end: string;
  kwh_contributed: number;
  amount_earned: number;
  status: string;
  tx_signature?: string;
};

type DashboardData = {
  surplus_this_period: number;
  cumulative_kwh: number;
  total_earned: number;
  period_start: string;
  period_end: string;
};

/** Live indicator dot */
export function LiveDot({ live }: { live: boolean }) {
  if (!live) return null;
  return (
    <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
      </span>
      Live
    </span>
  );
}

/** Merges realtime contribution updates into the history list. */
export function useRealtimeHistory(initialHistory: HistoryItem[]) {
  const [history, setHistory] = useState(initialHistory);
  const { lastChange, live } = useRealtimeTable<HistoryItem>("contributions");

  useEffect(() => {
    if (!lastChange) return;
    const { eventType, new: row } = lastChange;
    if (eventType === "INSERT") {
      setHistory((prev) => [row, ...prev]);
    } else if (eventType === "UPDATE") {
      setHistory((prev) => prev.map((h) => (h.id === row.id ? { ...h, ...row } : h)));
    } else if (eventType === "DELETE") {
      setHistory((prev) => prev.filter((h) => h.id !== lastChange.old.id));
    }
  }, [lastChange]);

  return { history, live };
}

/** Merges realtime pool updates into dashboard stats. */
export function useRealtimeDashboard(initial: DashboardData) {
  const [data, setData] = useState(initial);
  const { lastChange, live } = useRealtimeTable<Record<string, unknown>>("community_pool");

  useEffect(() => {
    if (!lastChange) return;
    // Re-fetch dashboard when pool changes — simplest correct approach
    // since dashboard is a server-computed aggregate
    fetch("/api/dashboard-refresh")
      .then((r) => r.json())
      .then((d) => setData(d))
      .catch(() => {});
  }, [lastChange]);

  return { data, live };
}
