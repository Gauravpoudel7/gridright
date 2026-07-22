/**
 * Server Actions for seller onboarding (spec §3.1).
 *
 * The application submit/status/resubmit flow is PUBLIC — the applicant has no
 * auth user until an operator approves them — so these actions call the FastAPI
 * backend without a session token. The operator review actions courier the
 * operator's Supabase token, which the backend independently verifies.
 */
"use server";

import { revalidatePath } from "next/cache";

import { createSupabaseServerClient } from "@/lib/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type SubmitApplicationResult = {
  ok: boolean;
  applicationId?: string;
  editToken?: string;
  error?: string;
};

/** Public: submit a new seller identity application. */
export async function submitApplicationAction(
  formData: FormData,
): Promise<SubmitApplicationResult> {
  const payload = {
    full_name: String(formData.get("full_name") ?? "").trim(),
    dob: String(formData.get("dob") ?? "").trim(),
    ownership_doc_url: String(formData.get("ownership_doc_url") ?? "").trim(),
    gmail: String(formData.get("gmail") ?? "").trim(),
    location_text: String(formData.get("location_text") ?? "").trim(),
  };

  for (const [k, v] of Object.entries(payload)) {
    if (!v) return { ok: false, error: `${k.replace(/_/g, " ")} is required` };
  }

  const res = await fetch(`${API_BASE}/api/v1/applications`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Submission failed (${res.status})` };
  }
  const data = await res.json();
  return { ok: true, applicationId: data.id, editToken: data.edit_token };
}

export type ApplicationStatusResult = {
  ok: boolean;
  status?: string;
  rejectionReason?: string | null;
  error?: string;
};

/** Public (token-gated): check an application's status. */
export async function checkApplicationStatusAction(
  applicationId: string,
  editToken: string,
): Promise<ApplicationStatusResult> {
  const res = await fetch(
    `${API_BASE}/api/v1/applications/${applicationId}/status?edit_token=${encodeURIComponent(editToken)}`,
    { cache: "no-store" },
  );
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Lookup failed (${res.status})` };
  }
  const data = await res.json();
  return { ok: true, status: data.application_status, rejectionReason: data.rejection_reason };
}

/** Public (token-gated): resubmit a rejected application. */
export async function resubmitApplicationAction(
  formData: FormData,
): Promise<SubmitApplicationResult> {
  const applicationId = String(formData.get("application_id") ?? "");
  const editToken = String(formData.get("edit_token") ?? "");
  if (!applicationId || !editToken) {
    return { ok: false, error: "Missing application id or edit token" };
  }

  const body: Record<string, string> = { edit_token: editToken };
  for (const field of ["full_name", "dob", "ownership_doc_url", "gmail", "location_text"]) {
    const v = String(formData.get(field) ?? "").trim();
    if (v) body[field] = v;
  }

  const res = await fetch(`${API_BASE}/api/v1/applications/${applicationId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Resubmission failed (${res.status})` };
  }
  return { ok: true, applicationId };
}

export type OperatorReviewResult = { ok: boolean; error?: string };

/** Operator: approve an application and assign a community pool. */
export async function approveApplicationAction(
  formData: FormData,
): Promise<OperatorReviewResult> {
  const applicationId = String(formData.get("application_id") ?? "");
  const communityPoolId = String(formData.get("community_pool_id") ?? "");
  if (!applicationId || !communityPoolId) {
    return { ok: false, error: "Application and community pool are required" };
  }

  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not signed in" };

  const res = await fetch(
    `${API_BASE}/api/v1/operator/applications/${applicationId}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ community_pool_id: communityPoolId }),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Approve failed (${res.status})` };
  }
  revalidatePath("/operator/dashboard");
  return { ok: true };
}

/** Operator: reject an application with a reason. */
export async function rejectApplicationAction(
  formData: FormData,
): Promise<OperatorReviewResult> {
  const applicationId = String(formData.get("application_id") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  if (!applicationId) return { ok: false, error: "Application is required" };
  if (!reason) return { ok: false, error: "A rejection reason is required" };

  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not signed in" };

  const res = await fetch(
    `${API_BASE}/api/v1/operator/applications/${applicationId}/reject`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ reason }),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Reject failed (${res.status})` };
  }
  revalidatePath("/operator/dashboard");
  return { ok: true };
}
