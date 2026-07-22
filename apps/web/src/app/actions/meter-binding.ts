/**
 * Server Actions for meter binding (spec §3.2).
 *
 * Couriers the seller's Supabase token to the FastAPI backend, which runs the
 * binding state machine (pairing-code exchange with the virtual-smart-meter
 * service, uniqueness, rate limiting).
 */
"use server";

import { revalidatePath } from "next/cache";

import { createSupabaseServerClient } from "@/lib/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type MeterBindingResult = {
  ok: boolean;
  status?: string;
  meterId?: string | null;
  reason?: string | null;
  error?: string;
};

export async function submitPairingCodeAction(
  formData: FormData,
): Promise<MeterBindingResult> {
  const pairingCode = String(formData.get("pairing_code") ?? "").trim();
  if (!pairingCode) return { ok: false, error: "A pairing code is required" };

  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not signed in" };

  const res = await fetch(`${API_BASE}/api/v1/sellers/me/meter-binding`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ pairing_code: pairingCode }),
    cache: "no-store",
  });

  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Binding failed (${res.status})` };
  }
  const data = await res.json();
  revalidatePath("/dashboard");
  return {
    ok: true,
    status: data.meter_binding_status,
    meterId: data.meter_id ?? null,
    reason: data.reason ?? null,
  };
}
