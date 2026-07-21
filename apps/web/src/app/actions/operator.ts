/**
 * Server Actions for operator review decisions.
 *
 * The action forwards the operator's Supabase access token to the FastAPI
 * backend, which independently verifies the operator role server-side —
 * this action is a courier, not the authority.
 */
"use server";

import { revalidatePath } from "next/cache";

import { createSupabaseServerClient } from "@/lib/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type ResolveResult = {
  ok: boolean;
  error?: string;
};

export async function resolveReviewAction(
  formData: FormData,
): Promise<ResolveResult> {
  const reviewId = String(formData.get("review_id") ?? "");
  const action = String(formData.get("action") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  const adjustedPriceRaw = String(formData.get("adjusted_price") ?? "").trim();

  if (!reviewId || !["approve", "adjust", "reject"].includes(action)) {
    return { ok: false, error: "Invalid review action" };
  }
  if (!reason) {
    return { ok: false, error: "A reason is required for every decision" };
  }

  let adjusted_price: number | undefined;
  if (action === "adjust") {
    adjusted_price = Number(adjustedPriceRaw);
    if (!adjustedPriceRaw || !Number.isFinite(adjusted_price) || adjusted_price < 0) {
      return { ok: false, error: "Adjust requires a valid non-negative price" };
    }
  }

  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) {
    return { ok: false, error: "Not signed in" };
  }

  const res = await fetch(`${API_BASE}/api/v1/reviews/${reviewId}/resolve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ action, reason, adjusted_price }),
    cache: "no-store",
  });

  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => b?.detail)
      .catch(() => null);
    return { ok: false, error: detail ?? `Request failed (${res.status})` };
  }

  revalidatePath("/operator/dashboard");
  return { ok: true };
}
