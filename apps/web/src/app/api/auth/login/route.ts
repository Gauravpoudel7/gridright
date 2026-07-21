/**
 * JSON endpoint for sign-in. The login pages use Server Actions for the
 * happy path; this route handler exists for clients that need a JSON
 * response (e.g. test harnesses, or external integrations).
 *
 * On success, returns the user profile and sets the Supabase session
 * cookies. On failure, returns 401 with the error message.
 */
import { NextResponse } from "next/server";

import { getCurrentUser } from "@/lib/supabase/get-current-user";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export async function POST(request: Request) {
  let body: { email?: string; password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body" },
      { status: 400 },
    );
  }

  const email = body.email?.trim();
  const password = body.password;
  if (!email || !password) {
    return NextResponse.json(
      { error: "Email and password are required" },
      { status: 400 },
    );
  }

  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 401 });
  }

  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.json(
      { error: "Signed in but profile not found" },
      { status: 500 },
    );
  }

  return NextResponse.json({
    id: user.id,
    email: user.email,
    role: user.role,
  });
}
