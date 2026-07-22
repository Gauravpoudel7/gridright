/**
 * Server Actions for wallet activation via signed challenge (spec §3.3).
 *
 * The nonce is issued and the signature verified SERVER-SIDE by the FastAPI
 * backend — these actions never assert "signature valid" themselves; they
 * courier the seller's token, the address, and the wallet's signature.
 */
"use server";

import { revalidatePath } from "next/cache";

import { createSupabaseServerClient } from "@/lib/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type WalletChallengeResult = {
  ok: boolean;
  nonce?: string;
  message?: string;
  error?: string;
};

export async function requestWalletChallengeAction(): Promise<WalletChallengeResult> {
  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not signed in" };

  const res = await fetch(`${API_BASE}/api/v1/sellers/me/wallet/challenge`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Challenge failed (${res.status})` };
  }
  const data = await res.json();
  return { ok: true, nonce: data.nonce, message: data.message };
}

export type WalletVerifyResult = {
  ok: boolean;
  walletStatus?: string;
  walletAddress?: string;
  applies?: string;
  error?: string;
};

export async function verifyWalletSignatureAction(
  address: string,
  nonce: string,
  signature: string,
): Promise<WalletVerifyResult> {
  const supabase = await createSupabaseServerClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;
  if (!token) return { ok: false, error: "Not signed in" };

  const res = await fetch(`${API_BASE}/api/v1/sellers/me/wallet/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ address, nonce, signature }),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => null);
    return { ok: false, error: detail ?? `Verification failed (${res.status})` };
  }
  const data = await res.json();
  revalidatePath("/dashboard");
  return {
    ok: true,
    walletStatus: data.wallet_status,
    walletAddress: data.wallet_address,
    applies: data.applies,
  };
}
