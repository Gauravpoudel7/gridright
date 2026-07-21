/**
 * Data Access Layer helper for the current authenticated user.
 *
 * Implements the Next.js Data Access Layer pattern: only runs on the
 * server, performs its own authorization check, and returns a minimal
 * DTO (never the raw auth user object). Wrapped with React `cache()` so
 * repeated calls within the same request don't re-fetch.
 *
 * Per the Next.js 16 data-security guide, pages and route handlers must
 * verify auth server-side — proxy.ts alone is not enough.
 *
 * Returns `null` if there is no session.
 */
import "server-only";
import { cache } from "react";

import { createSupabaseServerClient } from "./server";

export type CurrentUser = {
  id: string;
  email: string | null;
  role: "seller" | "operator";
};

export const getCurrentUser = cache(async (): Promise<CurrentUser | null> => {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();
  if (error || !user) return null;

  // Look up the role from the profiles table. Phase 1 schema:
  //   profiles (id uuid PK, role text, email text, ...)
  const { data: profile, error: profileError } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .single();

  if (profileError || !profile) return null;

  const role = profile.role as "seller" | "operator";

  return {
    id: user.id,
    email: user.email ?? null,
    role,
  };
});

export async function requireRole(
  required: "seller" | "operator",
): Promise<CurrentUser> {
  const user = await getCurrentUser();
  if (!user) {
    // Caller should redirect to login; this is a 401-equivalent.
    throw new Error("UNAUTHENTICATED");
  }
  if (user.role !== required) {
    // Caller should redirect away — 403-equivalent.
    throw new Error("FORBIDDEN");
  }
  return user;
}
