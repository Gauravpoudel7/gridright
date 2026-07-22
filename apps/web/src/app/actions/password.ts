/**
 * Server Action for the forced password change (spec §4).
 *
 * Couriers the seller's Supabase token to the FastAPI backend, which sets the
 * new password via the auth admin API and clears must_change_password. The
 * backend is the authority — this action is a courier.
 */
"use server";

import { revalidatePath } from "next/cache";

import { createSupabaseServerClient } from "@/lib/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type ChangePasswordResult = { ok: boolean; error?: string };

export async function changePasswordAction(
  formData: FormData,
): Promise<ChangePasswordResult> {
  const newPassword = String(formData.get("new_password") ?? "");
  const confirm = String(formData.get("confirm_password") ?? "");

  if (newPassword.length < 8) {
    return { ok: false, error: "Password must be at least 8 characters" };
  }
  if (newPassword !== confirm) {
    return { ok: false, error: "Passwords do not match" };
  }

  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not signed in" };

  const res = await fetch(`${API_BASE}/api/v1/sellers/me/change-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ new_password: newPassword }),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Password change failed (${res.status})` };
  }

  // The profile flag is cleared server-side; refresh any gated views.
  revalidatePath("/", "layout");
  return { ok: true };
}
