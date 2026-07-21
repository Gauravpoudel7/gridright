"use server";

import { createSupabaseServerClient } from "@/lib/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type WalletCheckResult = { ok: boolean; walletAddress?: string; error?: string };

/** Returns the current user's wallet_address from profiles. */
export async function getWalletAddress(): Promise<WalletCheckResult> {
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not authenticated" };

  const { data, error } = await supabase
    .from("profiles")
    .select("wallet_address")
    .eq("id", user.id)
    .single();

  if (error) return { ok: false, error: error.message };
  return { ok: true, walletAddress: data?.wallet_address ?? undefined };
}
