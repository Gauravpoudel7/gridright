// DEMO-ONLY — persistent banner shown across the /demo/live page so it
// can never be mistaken for the real production dashboards. Amber,
// fixed-position, "DEMO" wording. Purely visual.

import Link from "next/link";

export function DemoBanner() {
  return (
    <div
      role="status"
      aria-label="Demo mode active"
      className="sticky top-0 z-50 mb-6 flex items-center justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-amber-900 shadow-sm dark:border-amber-700 dark:bg-amber-950/60 dark:text-amber-200"
    >
      <div className="flex items-center gap-2">
        <span className="inline-flex h-5 items-center rounded bg-amber-600 px-2 text-[11px] font-bold uppercase tracking-wider text-white">
          DEMO
        </span>
        <p className="text-sm font-medium">
          Continuous simulation — no real Supabase, no real devnet, no login.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <p className="hidden text-xs text-amber-700 sm:block dark:text-amber-400">
          Data resets on reload
        </p>
        <Link
          href="/"
          className="whitespace-nowrap text-xs font-medium text-amber-800 underline-offset-2 hover:underline dark:text-amber-300"
        >
          ← Exit demo
        </Link>
      </div>
    </div>
  );
}
