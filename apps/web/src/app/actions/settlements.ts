/**
 * Server Actions for the 30-minute settlement cycle.
 *
 * The operator pays each payout line client-side via Phantom; these actions
 * courier the operator's token to the FastAPI backend, which records the tx
 * signature and completes the batch when the last line is paid.
 */
"use server";

import { revalidatePath } from "next/cache";

import { createSupabaseServerClient } from "@/lib/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type SettlementActionResult = {
  ok: boolean;
  batchCompleted?: boolean;
  error?: string;
};

export async function recordSettlementPaidAction(
  itemId: string,
  txSignature: string,
): Promise<SettlementActionResult> {
  if (!itemId || !txSignature) {
    return { ok: false, error: "Missing item id or transaction signature" };
  }

  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not signed in" };

  const res = await fetch(
    `${API_BASE}/api/v1/operator/settlements/items/${itemId}/paid`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ tx_signature: txSignature }),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Recording failed (${res.status})` };
  }
  const data = await res.json();
  revalidatePath("/operator/dashboard");
  return { ok: true, batchCompleted: data.batch_completed };
}

/** Manually trigger a settlement cycle run (also fired by the scheduler). */
export async function runSettlementCycleAction(): Promise<SettlementActionResult> {
  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not signed in" };

  const res = await fetch(`${API_BASE}/api/v1/settlements/run`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Run failed (${res.status})` };
  }
  revalidatePath("/operator/dashboard");
  return { ok: true };
}
