/**
 * Server Actions for authentication.
 *
 * Both the seller login page and the operator login page use the same
 * signInWithPassword action; the page just picks where to redirect after
 * sign-in. Role lookup happens via getCurrentUser() once the session is
 * established, so the wrong-role redirect only kicks in for the edge
 * case where a seller signs in via /operator/login (or vice versa).
 */
"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/supabase/get-current-user";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export type LoginResult = {
  ok: boolean;
  error?: string;
  /** Informational notice on success (e.g. "confirm your email"). */
  message?: string;
};

export async function loginAction(formData: FormData): Promise<LoginResult> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const next = String(formData.get("next") ?? "/dashboard");

  if (!email || !password) {
    return { ok: false, error: "Email and password are required" };
  }

  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) {
    return { ok: false, error: error.message };
  }

  // Re-validate auth state for this request, then redirect to `next`
  // (which the calling page set based on the entry point: /dashboard
  // for sellers, /operator/dashboard for operators).
  revalidatePath("/", "layout");
  const user = await getCurrentUser();

  if (!user) {
    return {
      ok: false,
      error: "Signed in but profile not found. Contact an admin.",
    };
  }

  // Defensive: the page already gated the role for the entry point, but
  // if a seller hits /operator/login (or vice versa), send them to the
  // correct dashboard with an error flag rather than letting them in.
  if (next.startsWith("/operator") && user.role !== "operator") {
    redirect("/login?error=not_operator");
  }
  if (!next.startsWith("/operator") && user.role === "operator") {
    redirect("/operator/login?error=not_seller");
  }

  redirect(next);
}

// NOTE: there is deliberately no signupAction. Seller accounts are created
// exclusively by an operator approving an application (see /apply and the
// onboarding endpoints) — self-serve signup would bypass identity review.

export async function logoutAction(): Promise<void> {
  const supabase = await createSupabaseServerClient();
  await supabase.auth.signOut();
  revalidatePath("/", "layout");
  redirect("/");
}
