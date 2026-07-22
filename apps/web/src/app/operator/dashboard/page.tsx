import { redirect } from "next/navigation";
import { cache } from "react";
import "server-only";

import { logoutAction } from "@/app/actions/auth";
import { getCurrentUser } from "@/lib/supabase/get-current-user";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { ReviewControls } from "./review-controls";
import { OperatorFeedClient } from "./operator-feed-client";
import { FleetOutlook, EMPTY_FLEET, type FleetOutlookData } from "./fleet-outlook";
import { ApplicationsReview } from "./applications-review";
import { SettlementPanel } from "./settlement-panel";

export const metadata = { title: "Operator dashboard — GridRight" };

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const getToken = cache(async (): Promise<string | null> => {
  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  return sessionData?.session?.access_token ?? null;
});

async function apiGet<T>(path: string, fallback: T): Promise<T> {
  const token = await getToken();
  if (!token) return fallback;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return fallback;
  return res.json();
}

function fmt(v: number, digits = 2) { return v.toFixed(digits); }
function fmtPrice(v: number) { return `$${v.toFixed(4)}`; }

function statCard(label: string, value: string, unit: string) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
        {value}<span className="ml-1 text-sm font-normal text-zinc-500">{unit}</span>
      </p>
    </div>
  );
}

function directionBadge(direction: string) {
  const styles =
    direction === "import" ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
    : direction === "export" ? "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400"
    : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400";
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles}`}>{direction.replace("_", " ")}</span>;
}

export default async function OperatorDashboardPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/operator/login");
  if (user.role !== "operator") redirect("/login?error=not_operator");

  const supabase = await createSupabaseServerClient();
  const { data: profile } = await supabase
    .from("profiles")
    .select("wallet_address")
    .eq("id", user.id)
    .single();

  const [feed, pendingReviews, pool, distribution, stats, fleet, applications, poolsRes, settlements] =
    await Promise.all([
      apiGet<any[]>("/api/v1/operator/feed", []),
      apiGet<any[]>("/api/v1/reviews/pending", []),
      apiGet<any>("/api/v1/operator/pool", { total_kwh_contributed: 0, current_absorption_kwh: 0, absorption_limit_kwh: 0, pending_import_export: [] }),
      apiGet<any[]>("/api/v1/operator/distribution", []),
      apiGet<any>("/api/v1/operator/stats", { total_kwh_settled: 0, total_payouts: 0, total_spread_captured: 0, average_uplift_percentage: 0, feed_in_tariff_reference: 0, settled_count: 0 }),
      apiGet<FleetOutlookData>("/api/v1/operator/fleet", EMPTY_FLEET),
      apiGet<any[]>("/api/v1/operator/applications", []),
      supabase.from("community_pool").select("id"),
      apiGet<any>("/api/v1/operator/settlements", { batch: null, items: [] }),
    ]);

  // community_pool has no name column in the Phase 1 schema — label pools by a
  // short id slice so the operator can still pick one.
  const pools = (poolsRes.data ?? []).map((p: { id: string }) => ({
    id: p.id,
    name: `Pool ${p.id.slice(0, 8)}`,
  }));

  const pricingExceptions = pendingReviews.filter((r: any) => r.direction === "local_pool");

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-12">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Operator dashboard</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Signed in as {user.email}</p>
        </div>
        <form action={logoutAction}>
          <button type="submit" className="rounded border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-900 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900">
            Sign out
          </button>
        </form>
      </header>

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statCard("Total spread captured", `$${fmt(stats.total_spread_captured)}`, "")}
        {statCard("Avg seller uplift over tariff", fmt(stats.average_uplift_percentage), "%")}
        {statCard("Settled energy", fmt(stats.total_kwh_settled), "kWh")}
        {statCard("Total payouts", `$${fmt(stats.total_payouts)}`, "")}
      </div>

      {/* 30-minute settlement cycle — payouts due this cycle */}
      <SettlementPanel batch={settlements.batch} initialItems={settlements.items ?? []} />

      {/* Identity review — pending seller applications */}
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Identity review</h2>
        <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
          Pending seller applications. On approve, the seller receives login credentials by email.
        </p>
        <ApplicationsReview initialApplications={applications} pools={pools} />
      </section>

      {/* Fleet outlook (Phase 4) */}
      <FleetOutlook data={fleet} />

      {/* Exception queue */}
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Exception queue</h2>
        <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">Recommendations outside the policy band.</p>
        {pricingExceptions.length === 0 ? (
          <p className="text-sm text-zinc-500">No pending exceptions.</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {pricingExceptions.map((review: any) => (
              <li key={review.id} className="rounded-lg border border-yellow-300 bg-yellow-50 p-4 dark:border-yellow-900/50 dark:bg-yellow-900/10">
                <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-zinc-900 dark:text-zinc-50">
                  <span className="font-medium">{fmt(review.kwh_contributed)} kWh @ {fmtPrice(review.ai_recommended_price)}/kWh</span>
                  {directionBadge(review.direction)}
                </div>
                <p className="mb-3 text-sm text-yellow-800 dark:text-yellow-400">{review.deviation_reason}</p>
                <ReviewControls reviewId={review.id} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Import/export panel */}
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Import / export</h2>
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {statCard("Pool contributed", fmt(pool.total_kwh_contributed), "kWh")}
          {statCard("Current absorption", fmt(pool.current_absorption_kwh), "kWh")}
          {statCard("Absorption limit", fmt(pool.absorption_limit_kwh), "kWh")}
        </div>
        {pool.pending_import_export.length === 0 ? (
          <p className="text-sm text-zinc-500">No pending import or export recommendations.</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {pool.pending_import_export.map((rec: any) => (
              <li key={rec.id} className="rounded-lg border border-blue-300 bg-blue-50 p-4 dark:border-blue-900/50 dark:bg-blue-900/10">
                <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                  {directionBadge(rec.direction)}
                  <span className="font-medium">{fmt(rec.kwh)} kWh @ {fmtPrice(rec.ai_recommended_price)}/kWh</span>
                </div>
                {rec.deviation_reason && (
                  <p className="mb-3 text-sm text-blue-800 dark:text-blue-400">{rec.deviation_reason}</p>
                )}
                <ReviewControls reviewId={rec.id} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Distribution */}
      <section className="mb-8 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-4 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Distribution by seller</h2>
        {distribution.length === 0 ? (
          <p className="text-sm text-zinc-500">No contributions yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
                <th className="pb-2 pr-4 font-medium">Seller</th>
                <th className="pb-2 pr-4 font-medium">Total kWh</th>
                <th className="pb-2 font-medium">Contributions</th>
              </tr>
            </thead>
            <tbody>
              {distribution.map((item: any) => (
                <tr key={item.seller_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/50">
                  <td className="py-2 pr-4 font-mono text-xs">{item.seller_id}</td>
                  <td className="py-2 pr-4">{fmt(item.total_kwh)}</td>
                  <td className="py-2">{item.contribution_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Live feed with wallet + payout */}
      <OperatorFeedClient
        initialFeed={feed}
        savedWalletAddress={profile?.wallet_address ?? null}
      />
    </div>
  );
}
