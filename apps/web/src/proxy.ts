/**
 * Next.js 16 Proxy (renamed from Middleware).
 *
 * Gating layer: stops navigation to the wrong dashboard based on the
 * caller's role. Per the Next.js 16 data-security guide, this is a
 * best-effort guard — each page ALSO enforces the role server-side via
 * getCurrentUser(). Do not rely on proxy.ts alone.
 *
 * For /operator/* paths:
 *   - no session         -> redirect to /operator/login
 *   - wrong role (seller)-> redirect to /login?error=not_operator
 *   - operator          -> continue
 *
 * For /dashboard/* paths (seller-only):
 *   - no session         -> redirect to /login
 *   - wrong role (operator)-> redirect to /operator/login?error=not_seller
 *   - seller            -> continue
 *
 * Matcher excludes /login, /operator/login, /api/*, /_next/*, and static
 * assets so we don't recursively redirect during the auth flow itself.
 */
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

type Role = "seller" | "operator";

export async function proxy(request: NextRequest) {
  const response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          for (const { name, value } of cookiesToSet) {
            request.cookies.set(name, value);
          }
          for (const { name, value, options } of cookiesToSet) {
            response.cookies.set(name, value, options);
          }
        },
      },
    },
  );

  // getUser() validates the session against Supabase Auth, which is what
  // we want here — we don't trust the JWT on its own.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const role: Role | null = user
    ? ((await supabase
        .from("profiles")
        .select("role")
        .eq("id", user.id)
        .single()
        .then((r) => r.data?.role as Role | undefined)) ?? null)
    : null;

  const pathname = request.nextUrl.pathname;

  // Operator-only paths
  if (pathname.startsWith("/operator/dashboard")) {
    if (!user) {
      return redirectTo(request, "/operator/login");
    }
    if (role !== "operator") {
      return redirectTo(request, "/login?error=not_operator");
    }
    return response;
  }

  // Seller-only paths
  if (pathname.startsWith("/dashboard")) {
    if (!user) {
      return redirectTo(request, "/login");
    }
    if (role === "operator") {
      return redirectTo(request, "/operator/login?error=not_seller");
    }
    return response;
  }

  return response;
}

function redirectTo(request: NextRequest, path: string) {
  return NextResponse.redirect(new URL(path, request.url));
}

export const config = {
  // /demo (DEMO-ONLY route) must NEVER be matched here — it is public by
  // design and works signed-out. Guarded by proxy-demo-exclusion.test.ts.
  matcher: [
    "/dashboard/:path*",
    "/operator/dashboard/:path*",
  ],
};
