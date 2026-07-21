/**
 * Server-side Supabase client factory for Next.js App Router.
 *
 * Creates a fresh client per request — never share across requests
 * (per @supabase/ssr's documentation). The `cookies` argument lets the
 * caller plug in the appropriate Next.js cookies API depending on the
 * context (proxy, server component, route handler, server action).
 */
import { createServerClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";

function envUrl(): string {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!url) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL is not set");
  }
  return url;
}

function envAnonKey(): string {
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!key) {
    throw new Error("NEXT_PUBLIC_SUPABASE_ANON_KEY is not set");
  }
  return key;
}

export async function createSupabaseServerClient(): Promise<SupabaseClient> {
  const cookieStore = await cookies();
  return createServerClient(envUrl(), envAnonKey(), {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Setting cookies from a Server Component is not allowed. This
          // path is taken by the proxy for actual session refresh; the
          // pages and route handlers should not be doing it. Swallow
          // the error here — the next request will get a fresh attempt.
        }
      },
    },
  });
}
