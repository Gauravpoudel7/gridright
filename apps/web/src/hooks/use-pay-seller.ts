"use client";

import { useWallet } from "@solana/wallet-adapter-react";
import { Connection, PublicKey, Transaction } from "@solana/web3.js";
import { useCallback, useState } from "react";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
// centsToLamports uses the shared PLACEHOLDER devnet rate — see lib/solana-constants.ts
import { centsToLamports } from "@/lib/solana-constants";

// Devnet RPC — PLACEHOLDER: swap for paid RPC in production
const DEVNET_RPC = "https://api.devnet.solana.com";
const PROGRAM_ID = new PublicKey("88HxyoRrb9NzqWfk34SCoqHZcMFxmmHg6XVNpcVPxoFL");

export type PayoutStatus = "idle" | "signing" | "pending" | "confirmed" | "failed";

export function usePaySeller() {
  const { publicKey, sendTransaction } = useWallet();
  const [status, setStatus] = useState<PayoutStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const pay = useCallback(
    async (opts: {
      contributionId: string;
      sellerWallet: string;
      settlementPda: string;
      payoutAmountCents: number;
    }) => {
      if (!publicKey || !sendTransaction) {
        setError("Operator wallet not connected");
        return;
      }

      setStatus("signing");
      setError(null);

      try {
        const connection = new Connection(DEVNET_RPC, "confirmed");

        // Build pay_seller instruction manually (no generated IDL client needed).
        // Discriminator from target/idl/gridright.json — sha256("global:pay_seller")[0..8]
        const discriminator = Buffer.from([193, 245, 214, 255, 208, 113, 43, 124]);

        const settlementPubkey = new PublicKey(opts.settlementPda);
        const sellerPubkey = new PublicKey(opts.sellerWallet);

        const { TransactionInstruction, SystemProgram } = await import("@solana/web3.js");

        const ix = new TransactionInstruction({
          programId: PROGRAM_ID,
          keys: [
            { pubkey: settlementPubkey, isSigner: false, isWritable: false },
            { pubkey: sellerPubkey, isSigner: false, isWritable: true },
            { pubkey: publicKey, isSigner: true, isWritable: true },
            { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
          ],
          data: discriminator,
        });

        const tx = new Transaction().add(ix);
        const { blockhash } = await connection.getLatestBlockhash();
        tx.recentBlockhash = blockhash;
        tx.feePayer = publicKey;

        const sig = await sendTransaction(tx, connection);

        // Write pending status immediately
        const supabase = getSupabaseBrowserClient();
        await supabase
          .from("contributions")
          .update({ tx_signature: sig, status: "pending" })
          .eq("id", opts.contributionId);

        setStatus("pending");

        // Confirm on-chain then flip to confirmed/failed
        connection
          .confirmTransaction(sig, "confirmed")
          .then(async (result) => {
            const newStatus = result.value.err ? "failed" : "confirmed";
            setStatus(newStatus as PayoutStatus);
            await supabase
              .from("contributions")
              .update({ status: newStatus === "confirmed" ? "settled" : "pending" })
              .eq("id", opts.contributionId);
          })
          .catch(() => setStatus("failed"));
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Transaction failed");
        setStatus("failed");
      }
    },
    [publicKey, sendTransaction],
  );

  return { pay, status, error };
}
