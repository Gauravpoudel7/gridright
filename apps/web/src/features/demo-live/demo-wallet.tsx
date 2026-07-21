// DEMO-ONLY — visual twin of apps/web/src/components/wallet-connect.tsx.
// Shows the same "Phantom wallet" header, the same truncated pubkey
// formatting, the same "Devnet" pill, and a button that simulates a
// connect flow with the same `wallet-adapter-button` class names —
// but never touches a real wallet, Supabase, or RPC. The "DEMO"
// prefix on the fake pubkey makes it visually obvious nothing real
// is connected.

import { useState } from "react";
import {
  DEMO_OPERATOR_PUBKEY,
  DEMO_SELLER_PUBKEY,
} from "./sim";

type DemoWalletProps = {
  /** "seller" shows the seller's wallet; "operator" shows the operator's. */
  role: "seller" | "operator";
  /** "demo-seller" / "demo-operator" — different copy on the button. */
  prompt: string;
};

type ConnectState = "disconnected" | "connecting" | "connected";

const APP_IS_DEVNET = true; // mirrors wallet-connect.tsx default

function truncate(addr: string): string {
  return `${addr.slice(0, 4)}…${addr.slice(-4)}`;
}

export function DemoWallet({ role, prompt }: DemoWalletProps) {
  const [state, setState] = useState<ConnectState>("connected");
  const pubkey = role === "seller" ? DEMO_SELLER_PUBKEY : DEMO_OPERATOR_PUBKEY;
  const label = role === "seller" ? "Phantom wallet" : "Operator Phantom wallet";
  const headerNote = role === "operator"
    ? "Connect an operator wallet to approve settlements"
    : "Connect a wallet to list surplus";

  const onClick = () => {
    if (state !== "disconnected") return;
    setState("connecting");
    // Mirror the wallet-adapter's natural "opening modal" delay so the
    // connect button looks alive.
    setTimeout(() => setState("connected"), 800);
  };

  // Same height/font/padding/radius as the real WalletMultiButton so the
  // card is the same size on the page.
  const buttonStyle = {
    height: "36px",
    fontSize: "14px",
    padding: "0 12px",
    borderRadius: "6px",
  } as const;

  const buttonLabel =
    state === "disconnected"
      ? prompt
      : state === "connecting"
        ? "Opening…"
        : "Connected";

  return (
    <div className="mb-6 flex items-center justify-between rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
      <div>
        <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
          {label}
        </p>
        {state === "connected" ? (
          <>
            <p className="font-mono text-xs text-zinc-500">
              Saved: {truncate(pubkey)}
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              {role === "operator" ? "Operator wallet" : "Seller wallet"} ready
              for {role === "operator" ? "settlement approval" : "listing surplus"}.
            </p>
          </>
        ) : (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            {headerNote}
          </p>
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onClick}
          disabled={state !== "disconnected"}
          className="wallet-adapter-button wallet-adapter-button-trigger"
          style={{
            ...buttonStyle,
            // The real WalletMultiButton uses these utility-classes
            // internally; we apply them inline so the demo button is
            // visually indistinguishable from the real one.
            backgroundColor: state === "disconnected" ? "#9945FF" : "#14F195",
            color: state === "disconnected" ? "white" : "#0f172a",
            cursor: state === "disconnected" ? "pointer" : "default",
            border: "none",
            fontWeight: 500,
          }}
        >
          {buttonLabel}
        </button>
        {state === "connected" && (
          <>
            <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
              {truncate(pubkey)}
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
    </div>
  );
}
