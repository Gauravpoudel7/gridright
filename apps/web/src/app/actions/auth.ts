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

export async function signupAction(formData: FormData): Promise<LoginResult> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const displayName = String(formData.get("display_name") ?? "").trim();

  if (!email || !password) {
    return { ok: false, error: "Email and password are required" };
  }
  if (password.length < 6) {
    return { ok: false, error: "Password must be at least 6 characters" };
  }

  const supabase = await createSupabaseServerClient();
  // Public signup always creates a seller — the on_auth_user_created
  // trigger writes the profiles row with role 'seller'. Operator accounts
  // are provisioned by an admin, never through this form.
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: displayName ? { display_name: displayName } : undefined,
    },
  });

  if (error) {
    return { ok: false, error: error.message };
  }

  // With email confirmations enabled there is no session yet — tell the
  // user to check their inbox instead of redirecting into a 401.
  if (!data.session) {
    return {
      ok: true,
      message: "Check your email to confirm your account, then sign in.",
    };
  }

  revalidatePath("/", "layout");
  redirect("/dashboard");
}

export async function logoutAction(): Promise<void> {
  const supabase = await createSupabaseServerClient();
  await supabase.auth.signOut();
  revalidatePath("/", "layout");
  redirect("/");
}
