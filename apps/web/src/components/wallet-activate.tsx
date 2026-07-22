"use client";

import { useWallet } from "@solana/wallet-adapter-react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import { useState } from "react";

import {
  requestWalletChallengeAction,
  verifyWalletSignatureAction,
} from "@/app/actions/wallet-activation";

type WalletStatus = "not_connected" | "active";

/**
 * Wallet activation via a signed challenge (spec §3.3, §4).
 *
 * Unlike the legacy WalletConnect (which trusted the browser and wrote the
 * address straight to profiles), this flow proves ownership:
 *   1. ask the backend for a single-use nonce,
 *   2. have the wallet sign the challenge message with signMessage,
 *   3. send {address, nonce, signature} to the backend, which verifies the
 *      ed25519 signature SERVER-SIDE before accepting the address.
 * The client never asserts the signature is valid — the backend decides.
 *
 * Available only once the meter is bound and the password has been changed;
 * the parent gates rendering on those, and the backend enforces them too.
 */
export function WalletActivate({
  initialStatus,
  initialAddress,
}: {
  initialStatus: WalletStatus;
  initialAddress: string | null;
}) {
  const { publicKey, connected, signMessage } = useWallet();
  const [status, setStatus] = useState<WalletStatus>(initialStatus);
  const [address, setAddress] = useState<string | null>(initialAddress);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function activate() {
    setError(null);
    setNotice(null);
    if (!connected || !publicKey) {
      setError("Connect a wallet first.");
      return;
    }
    if (!signMessage) {
      setError("This wallet does not support message signing.");
      return;
    }
    setBusy(true);
    try {
      const challenge = await requestWalletChallengeAction();
      if (!challenge.ok || !challenge.nonce || !challenge.message) {
        setError(challenge.error ?? "Could not start wallet verification.");
        return;
      }

      // Sign the exact challenge message the backend will reconstruct.
      const signatureBytes = await signMessage(
        new TextEncoder().encode(challenge.message),
      );
      // base64-encode for transport — spread on large Uint8Array is unsafe,
      // use Array.from to iterate byte-by-byte.
      const signature = btoa(Array.from(signatureBytes, (b) => String.fromCharCode(b)).join(""));

      const result = await verifyWalletSignatureAction(
        publicKey.toBase58(),
        challenge.nonce,
        signature,
      );
      if (!result.ok) {
        setError(result.error ?? "Verification failed.");
        return;
      }
      setStatus((result.walletStatus as WalletStatus) ?? "active");
      setAddress(result.walletAddress ?? publicKey.toBase58());
      setNotice(
        result.applies === "next_settlement_cycle"
          ? "Wallet updated — takes effect from the next settlement cycle."
          : "Wallet activated. You can now list surplus for settlement.",
      );
    } catch (e) {
      // A user rejecting the signature in their wallet lands here.
      setError(e instanceof Error ? e.message : "Signing was cancelled.");
    } finally {
      setBusy(false);
    }
  }

  const buttonStyle = {
    height: "36px",
    fontSize: "14px",
    padding: "0 12px",
    borderRadius: "6px",
  } as const;

  return (
    <section className="mb-6 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
          Payout wallet
        </h2>
        <span
          className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
            status === "active"
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400"
              : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400"
          }`}
        >
          {status === "active" ? "active" : "not connected"}
        </span>
      </div>

      {status === "active" && address && (
        <p className="mb-3 text-sm text-zinc-700 dark:text-zinc-300">
          Active wallet:{" "}
          <span className="font-mono text-xs">
            {address.slice(0, 6)}…{address.slice(-6)}
          </span>
        </p>
      )}

      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        Connect your wallet and sign a one-time challenge to prove ownership.
        {status === "active" && " Signing again with a different wallet updates your payout address from the next cycle."}
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <WalletMultiButton style={buttonStyle} />
        <button
          type="button"
          onClick={activate}
          disabled={busy || !connected}
          className="h-9 rounded bg-zinc-900 px-4 text-sm font-medium text-zinc-50 hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
        >
          {busy ? "Verifying…" : status === "active" ? "Update wallet" : "Verify & activate"}
        </button>
      </div>

      {notice && (
        <p className="mt-3 text-sm text-emerald-700 dark:text-emerald-400">{notice}</p>
      )}
      {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </section>
  );
}
