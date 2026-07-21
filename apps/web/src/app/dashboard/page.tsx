import { redirect } from "next/navigation";
import { cache } from "react";
import "server-only";

import { logoutAction } from "@/app/actions/auth";
import { getCurrentUser } from "@/lib/supabase/get-current-user";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { SellerDashboardClient } from "./seller-dashboard-client";
import { MeterSection } from "@/components/meter-section";

export const metadata = { title: "Seller dashboard — GridRight" };

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const fetchDashboard = cache(async () => {
  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { surplus_this_period: 0, cumulative_kwh: 0, total_earned: 0, period_start: "", period_end: "" };
  const res = await fetch(`${API_BASE}/api/v1/sellers/me/dashboard`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return { surplus_this_period: 0, cumulative_kwh: 0, total_earned: 0, period_start: "", period_end: "" };
  return res.json();
});

const fetchHistory = cache(async () => {
  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return [];
  const res = await fetch(`${API_BASE}/api/v1/sellers/me/history`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return [];
  return res.json();
});

const fetchMeter = cache(async () => {
  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { device: null, readings: [] };
  const res = await fetch(`${API_BASE}/api/v1/sellers/me/meter`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return { device: null, readings: [] };
  return res.json();
});

export default async function SellerDashboardPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (user.role !== "seller") redirect("/operator/login?error=not_seller");

  const supabase = await createSupabaseServerClient();
  const { data: profile } = await supabase
    .from("profiles")
    .select("wallet_address")
    .eq("id", user.id)
    .single();

  const [dashboard, history, meter] = await Promise.all([fetchDashboard(), fetchHistory(), fetchMeter()]);

  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-12">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Seller dashboard</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Signed in as {user.email}</p>
        </div>
        <form action={logoutAction}>
          <button type="submit" className="rounded border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-900 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900">
            Sign out
          </button>
        </form>
      </header>

      <MeterSection
        sellerId={user.id}
        initialDevice={meter.device ?? null}
        initialReadings={meter.readings ?? []}
      />

      <SellerDashboardClient
        initialDashboard={dashboard}
        initialHistory={history}
        savedWalletAddress={profile?.wallet_address ?? null}
      />

      <div className="mt-4 flex justify-end">
        <a
          href={`${API_BASE}/api/v1/sellers/me/history/export`}
          className="rounded border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          Export CSV
        </a>
      </div>
    </div>
  );
}
