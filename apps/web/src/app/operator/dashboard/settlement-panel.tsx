"use client";

import { useWallet } from "@solana/wallet-adapter-react";
import { useState } from "react";

import {
  recordSettlementPaidAction,
  runSettlementCycleAction,
} from "@/app/actions/settlements";
import { centsToLamports } from "@/lib/solana-constants";

// Devnet RPC — PLACEHOLDER, mirrors use-pay-seller.ts
const DEVNET_RPC =
  process.env.NEXT_PUBLIC_SOLANA_RPC ?? "https://api.devnet.solana.com";

export type SettlementItem = {
  id: string;
  seller_id: string;
  payout_wallet: string;
  total_kwh: number;
  total_amount: number;
  contribution_count: number;
  missed_cycles: number;
  escalated: boolean;
  paid: boolean;
  tx_signature: string | null;
  /** "manual" (operator via Phantom) or "auto" (server auto-pay); null if unpaid. */
  paid_method?: "manual" | "auto" | null;
};

export type SettlementBatch = {
  id: string;
  cycle_start: string;
  due_at: string;
  escalated: boolean;
} | null;

function fmtMoney(v: number) {
  return `$${v.toFixed(2)}`;
}

function shortAddr(a: string) {
  return `${a.slice(0, 4)}…${a.slice(-4)}`;
}

/**
 * 30-minute settlement cycle panel. Shows the current due batch with one
 * payout line per seller; the operator pays each line via a plain Phantom
 * SOL transfer to the line's snapshotted payout_wallet, then the tx signature
 * is recorded server-side.
 *
 * Missed-deadline rule surfaced here: lines carried from earlier cycles show
 * an amber "missed ×N" badge; at 3 consecutive misses (~90 min) the line and
 * batch turn red ("escalated") — pay these first.
 */
export function SettlementPanel({
  batch,
  initialItems,
}: {
  batch: SettlementBatch;
  initialItems: SettlementItem[];
}) {
  const { publicKey, sendTransaction } = useWallet();
  const [items, setItems] = useState(initialItems);
  const [paying, setPaying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function runCycle() {
    setRunning(true);
    setError(null);
    const r = await runSettlementCycleAction();
    if (!r.ok) setError(r.error ?? "Run failed");
    setRunning(false);
  }

  async function payItem(item: SettlementItem) {
    setError(null);
    if (!publicKey || !sendTransaction) {
      setError("Connect the operator wallet first.");
      return;
    }
    setPaying(item.id);
    try {
      const { Connection, PublicKey, SystemProgram, Transaction } =
        await import("@solana/web3.js");
      const connection = new Connection(DEVNET_RPC, "confirmed");

      const lamports = centsToLamports(Math.round(item.total_amount * 100));
      const tx = new Transaction().add(
        SystemProgram.transfer({
          fromPubkey: publicKey,
          toPubkey: new PublicKey(item.payout_wallet),
          lamports,
        }),
      );
      const { blockhash } = await connection.getLatestBlockhash();
      tx.recentBlockhash = blockhash;
      tx.feePayer = publicKey;

      const sig = await sendTransaction(tx, connection);

      const recorded = await recordSettlementPaidAction(item.id, sig);
      if (!recorded.ok) {
        setError(recorded.error ?? "Payment sent but recording failed");
        return;
      }
      setItems((prev) =>
        prev.map((i) =>
          i.id === item.id ? { ...i, paid: true, tx_signature: sig } : i,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Transaction failed");
    } finally {
      setPaying(null);
    }
  }

  const unpaid = items.filter((i) => !i.paid);
  const hasEscalated = items.some((i) => i.escalated && !i.paid);

  return (
    <section
      className={`mb-8 rounded-lg border bg-white p-6 dark:bg-zinc-950 ${
        hasEscalated
          ? "border-red-400 dark:border-red-900"
          : "border-zinc-200 dark:border-zinc-800"
      }`}
    >
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
          Settlement cycle
        </h2>
        <button
          type="button"
          onClick={runCycle}
          disabled={running}
          className="h-8 rounded border border-zinc-300 px-3 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          {running ? "Running…" : "Run cycle now"}
        </button>
      </div>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        Payouts batch every 30 minutes. Unpaid lines roll into the next cycle
        and escalate after 3 misses.
      </p>

      {hasEscalated && (
        <p className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm font-medium text-red-800 dark:border-red-900/50 dark:bg-red-900/10 dark:text-red-400">
          Escalated payouts overdue ≥3 cycles — pay these immediately.
        </p>
      )}

      {!batch || items.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No payouts due this cycle. New surplus batches at the next run.
        </p>
      ) : (
        <>
          <p className="mb-3 text-xs text-zinc-500">
            Batch due by{" "}
            <span className="font-medium text-zinc-700 dark:text-zinc-300">
              {new Date(batch.due_at).toLocaleTimeString()}
            </span>
            {" · "}
            {unpaid.length} of {items.length} unpaid
          </p>
          <ul className="flex max-h-80 flex-col gap-3 overflow-y-auto">
            {items.map((item) => (
              <li
                key={item.id}
                className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 ${
                  item.escalated && !item.paid
                    ? "border-red-300 bg-red-50 dark:border-red-900/50 dark:bg-red-900/10"
                    : "border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900"
                }`}
              >
                <div>
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                    {fmtMoney(item.total_amount)}{" "}
                    <span className="font-normal text-zinc-500">
                      · {item.total_kwh.toFixed(2)} kWh ·{" "}
                      {item.contribution_count} contribution
                      {item.contribution_count === 1 ? "" : "s"}
                    </span>
                  </p>
                  <p className="font-mono text-xs text-zinc-500">
                    → {shortAddr(item.payout_wallet)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {item.missed_cycles > 0 && !item.paid && (
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        item.escalated
                          ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
                          : "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400"
                      }`}
                    >
                      {item.escalated ? "escalated · " : ""}missed ×
                      {item.missed_cycles}
                    </span>
                  )}
                  {item.paid ? (
                    <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400">
                      {item.paid_method === "auto" ? "paid · auto" : "paid"}
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => payItem(item)}
                      disabled={paying !== null}
                      className="h-8 rounded bg-zinc-900 px-3 text-xs font-medium text-zinc-50 hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
                    >
                      {paying === item.id ? "Paying…" : "Pay"}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {error && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>
      )}
    </section>
  );
}
