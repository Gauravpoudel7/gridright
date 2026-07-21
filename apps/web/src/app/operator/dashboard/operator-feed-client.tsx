"use client";

import { useEffect, useState } from "react";
import { WalletConnect } from "@/components/wallet-connect";
import { useWallet } from "@solana/wallet-adapter-react";
import { useRealtimeTable, } from "@/hooks/use-realtime-table";
import { LiveDot } from "@/components/realtime-dashboard";
import { usePaySeller, type PayoutStatus } from "@/hooks/use-pay-seller";

type FeedItem = {
  id: string;
  seller_id: string;
  kwh_contributed: number;
  ai_recommended_price: number;
  final_approved_price: number;
  approval_type: string | null;
  approval_reason: string | null;
  status: string;
  direction: string;
  deviation_reason: string | null;
  created_at: string;
  seller_wallet?: string;
  settlement_pda?: string;
  payout_amount_cents?: number;
};

function fmt(v: number, d = 2) { return v.toFixed(d); }
function fmtPrice(v: number) { return `$${v.toFixed(4)}`; }

function statusBadge(status: string) {
  const styles =
    status === "settled" ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
    : status === "needs_review" ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
    : status === "rejected" ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
    : status === "pending" ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
    : "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400";
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles}`}>{status.replace("_", " ")}</span>;
}

function PayButton({ item, walletOk }: { item: FeedItem; walletOk: boolean }) {
  const { pay, status, error } = usePaySeller();
  const canPay = walletOk && item.seller_wallet && item.settlement_pda && item.payout_amount_cents;

  if (!canPay) {
    return (
      <span className="text-xs text-zinc-400">
        {!walletOk ? "Connect operator wallet to pay" : "Missing seller wallet or settlement PDA"}
      </span>
    );
  }

  const label: Record<PayoutStatus, string> = {
    idle: "Pay seller",
    signing: "Signing…",
    pending: "Confirming…",
    confirmed: "Paid ✓",
    failed: "Failed — retry",
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        disabled={status === "signing" || status === "pending" || status === "confirmed"}
        onClick={() => pay({
          contributionId: item.id,
          sellerWallet: item.seller_wallet!,
          settlementPda: item.settlement_pda!,
          payoutAmountCents: item.payout_amount_cents!,
        })}
        className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
      >
        {label[status]}
      </button>
      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
}

export function OperatorFeedClient({
  initialFeed,
  savedWalletAddress,
}: {
  initialFeed: FeedItem[];
  savedWalletAddress: string | null;
}) {
  const { publicKey, connected } = useWallet();
  const [feed, setFeed] = useState(initialFeed);
  const { lastChange, live } = useRealtimeTable<FeedItem>("contributions");
  const [walletSaved, setWalletSaved] = useState(!!savedWalletAddress);

  useEffect(() => {
    if (connected && publicKey) setWalletSaved(true);
  }, [connected, publicKey]);

  useEffect(() => {
    if (!lastChange) return;
    const { eventType, new: row } = lastChange;
    if (eventType === "UPDATE") {
      setFeed((prev) => prev.map((f) => (f.id === row.id ? { ...f, ...row } : f)));
    } else if (eventType === "INSERT") {
      setFeed((prev) => [row, ...prev]);
    }
  }, [lastChange]);

  const walletOk = walletSaved || (connected && !!publicKey);

  return (
    <div>
      {/* Wallet connect row */}
      <div className="mb-6 flex items-center justify-between rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <div>
          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Operator Phantom wallet</p>
          {savedWalletAddress && !connected && (
            <p className="font-mono text-xs text-zinc-500">
              Saved: {savedWalletAddress.slice(0, 4)}…{savedWalletAddress.slice(-4)}
            </p>
          )}
          {!walletOk && (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              Connect a wallet to approve settlements
            </p>
          )}
        </div>
        <WalletConnect />
      </div>

      {/* Feed */}
      <section className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-4 flex items-center gap-2">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Recommendation feed</h2>
          <LiveDot live={live} />
        </div>
        {feed.length === 0 ? (
          <p className="text-sm text-zinc-500">No recommendations yet.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {feed.map((item) => (
              <li key={item.id} className="border-b border-zinc-100 pb-3 last:border-0 last:pb-0 dark:border-zinc-800/50">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-900 dark:text-zinc-50">
                  <span className="font-medium">{fmt(item.kwh_contributed)} kWh @ {fmtPrice(item.final_approved_price)}/kWh</span>
                  {statusBadge(item.status)}
                  {item.approval_type && (
                    <span className="text-xs text-zinc-500">
                      {item.approval_type === "auto" ? "auto-approved" : "human decision"}
                    </span>
                  )}
                </div>
                {item.approval_reason && (
                  <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">Reason: {item.approval_reason}</p>
                )}
                <p className="mt-1 text-xs text-zinc-500">{new Date(item.created_at).toLocaleString()}</p>
                {item.status === "settled" && (
                  <div className="mt-2">
                    <PayButton item={item} walletOk={walletOk} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
