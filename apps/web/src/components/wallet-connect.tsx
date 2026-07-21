"use client";

import { useWallet } from "@solana/wallet-adapter-react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import { useEffect, useRef, useSyncExternalStore } from "react";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

// Hydration-safe "are we on the client yet" flag. useSyncExternalStore returns
// the server snapshot (false) during SSR and the first client render, then the
// client snapshot (true) — without a setState-in-effect (disallowed by the
// react-hooks lint rules here).
const emptySubscribe = () => () => {};
function useMounted(): boolean {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
}

// The dapp's configured RPC — the wallet adapter routes reads/writes through
// this endpoint, so its cluster is the cluster the dapp is on. We compare
// against the well-known devnet URL (and common alternatives) so the seller
// gets a clear "switch Phantom to Devnet" warning when the dapp is on devnet
// but Phantom is on mainnet/testnet.
const APP_RPC =
  process.env.NEXT_PUBLIC_SOLANA_RPC ?? "https://api.devnet.solana.com";
const APP_IS_DEVNET = /devnet/i.test(APP_RPC);

/**
 * Wallet connect button that saves the connected pubkey to profiles.wallet_address.
 * Shown in both seller and operator dashboard headers.
 */
export function WalletConnect() {
  const { publicKey, connected } = useWallet();
  const savedKey = useRef<string | null>(null);

  // WalletMultiButton's label depends on browser-only wallet detection, so
  // its server HTML ("Select Wallet") never matches the client's first render.
  // Render a stable placeholder until mounted to avoid a hydration mismatch.
  const mounted = useMounted();

  useEffect(() => {
    if (!connected || !publicKey) return;
    const addr = publicKey.toBase58();
    if (savedKey.current === addr) return;
    savedKey.current = addr;

    const supabase = getSupabaseBrowserClient();
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) return;
      supabase
        .from("profiles")
        .update({ wallet_address: addr })
        .eq("id", data.user.id)
        .then(({ error }) => {
          if (error) console.error("Failed to save wallet address:", error.message);
        });
    });
  }, [connected, publicKey]);

  const buttonStyle = {
    height: "36px",
    fontSize: "14px",
    padding: "0 12px",
    borderRadius: "6px",
  } as const;

  if (!mounted) {
    // Matches WalletMultiButton's markup/classes so the swap-in is seamless.
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="wallet-adapter-button wallet-adapter-button-trigger"
          style={buttonStyle}
          disabled
        >
          Select Wallet
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <WalletMultiButton style={buttonStyle} />
      {connected && publicKey && (
        <>
          <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
            {publicKey.toBase58().slice(0, 4)}…{publicKey.toBase58().slice(-4)}
          </span>
          {APP_IS_DEVNET && (
            <span
              className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400"
              title="Dapp RPC is on devnet. Make sure your wallet is also on Devnet to see payouts."
            >
              Devnet
            </span>
          )}
        </>
      )}
    </div>
  );
}
