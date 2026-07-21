// DEMO-ONLY: safe to delete — remove this file along with src/features/demo/,
// src/app/demo/, and the "Try the Demo" button on src/app/page.tsx
//
// Performs a REAL devnet SOL transfer from the operator wallet to the seller
// wallet, mirroring the production settlement leg (operator pays seller) but on
// devnet with a deliberately tiny amount. The operator secret key is loaded
// from a local keypair file and NEVER leaves the server — the browser only ever
// sees the resulting transaction signature.
//
// Devnet SOL is limited, so DEMO_PAYOUT_SOL defaults to 0.001 SOL: enough to
// prove a genuine on-chain transfer without draining the faucet-funded wallet.
"use server";

import { readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import {
  Connection,
  Keypair,
  LAMPORTS_PER_SOL,
  PublicKey,
  SystemProgram,
  Transaction,
  sendAndConfirmTransaction,
} from "@solana/web3.js";

const DEVNET_RPC = process.env.DEMO_DEVNET_RPC ?? "https://api.devnet.solana.com";

// The operator (payer). Its secret key stays server-side. Defaults to the
// Solana CLI's default keypair, which the demo assumes is faucet-funded.
const OPERATOR_KEYPAIR_PATH =
  process.env.DEMO_OPERATOR_KEYPAIR ??
  path.join(os.homedir(), ".config", "solana", "id.json");

// The seller (recipient) devnet address. Defaults to the CLI's buyer.json
// address so the demo works out of the box on this machine.
const SELLER_WALLET =
  process.env.DEMO_SELLER_WALLET ?? "3VVoZKsc4HGtrACTGF35jo63wEKojSfQem9yggtXzb6F";

// Tiny on purpose — devnet SOL is a limited resource.
const PAYOUT_SOL = Number(process.env.DEMO_PAYOUT_SOL ?? "0.001");

export type DemoPayoutResult = {
  ok: boolean;
  signature?: string;
  explorerUrl?: string;
  operator?: string;
  seller?: string;
  lamports?: number;
  error?: string;
};

async function loadOperatorKeypair(): Promise<Keypair> {
  const raw = await readFile(OPERATOR_KEYPAIR_PATH, "utf8");
  const secret = Uint8Array.from(JSON.parse(raw) as number[]);
  return Keypair.fromSecretKey(secret);
}

/**
 * Send PAYOUT_SOL from the operator keypair to the seller wallet on devnet and
 * return the confirmed transaction signature. `sellerOverride` lets the caller
 * (the demo UI) pay the seller's *connected* wallet instead of the hardcoded
 * default — so the seller actually sees funds land in their own devnet account.
 * All failures are returned as a structured error so the demo UI can fall back
 * to a simulated confirmation rather than crash.
 */
export async function payDemoSeller(sellerOverride?: string): Promise<DemoPayoutResult> {
  try {
    // Trust the override if it parses as a valid pubkey; otherwise fall back
    // to the env default. This way a stale/missing override (e.g. user hasn't
    // connected) doesn't break the demo — it just uses the canonical address.
    const seller = new PublicKey(sellerOverride && sellerOverride.length > 0 ? sellerOverride : SELLER_WALLET);
    const operator = await loadOperatorKeypair();
    const lamports = Math.round(PAYOUT_SOL * LAMPORTS_PER_SOL);

    const connection = new Connection(DEVNET_RPC, "confirmed");

    // Guard against draining / an unfunded operator: need the payout plus a
    // little headroom for the fee.
    const balance = await connection.getBalance(operator.publicKey);
    if (balance < lamports + 5000) {
      return {
        ok: false,
        error: `Operator devnet balance too low (${(balance / LAMPORTS_PER_SOL).toFixed(
          4,
        )} SOL) to send ${PAYOUT_SOL} SOL`,
      };
    }

    const tx = new Transaction().add(
      SystemProgram.transfer({
        fromPubkey: operator.publicKey,
        toPubkey: seller,
        lamports,
      }),
    );

    const signature = await sendAndConfirmTransaction(connection, tx, [operator], {
      commitment: "confirmed",
    });

    return {
      ok: true,
      signature,
      explorerUrl: `https://explorer.solana.com/tx/${signature}?cluster=devnet`,
      operator: operator.publicKey.toBase58(),
      seller: seller.toBase58(),
      lamports,
    };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Unknown devnet transfer error",
    };
  }
}
