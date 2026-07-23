/**
 * Auto-pay — server-side settlement payout transfer.
 *
 * Called by the backend auto-pay job (apps/api app/services/autopay.py) for
 * non-escalated settlement items at or below the AUTOPAY_MAX_USD threshold.
 * Plain SystemProgram transfer from the server keypair to the seller's
 * snapshotted payout wallet. Prints a single JSON line:
 *   {"signature": "...", "wallet": "...", "amount_cents": N, "lamports": "N"}
 *
 * The cents→lamports rate MUST match apps/web/src/lib/solana-constants.ts and
 * the on-chain program (SOL_PRICE_CENTS) — auto and manual payments for the
 * same dollar amount must move the same lamports.
 *
 * Usage:
 *   npx tsx scripts/pay-settlement.ts \
 *     --wallet <base58 pubkey> \
 *     --amount-cents 483
 */
import {
  Connection,
  Keypair,
  PublicKey,
  SystemProgram,
  Transaction,
  sendAndConfirmTransaction,
} from "@solana/web3.js";
import fs from "fs";
import os from "os";
import path from "path";

const RPC = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";
const WALLET = process.env.SOLANA_WALLET ?? path.join(os.homedir(), ".config", "solana", "id.json");

// PLACEHOLDER fixed devnet rate (1 SOL = $150) — keep in sync with
// apps/web/src/lib/solana-constants.ts and programs/gridright/src/lib.rs.
const SOL_PRICE_CENTS = 15_000;
const LAMPORTS_PER_SOL = 1_000_000_000;

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

async function main() {
  const wallet = arg("wallet");
  const amountCentsRaw = arg("amount-cents");
  if (!wallet || !amountCentsRaw) {
    console.error("Required: --wallet <base58 pubkey>, --amount-cents N");
    process.exit(1);
  }
  const amountCents = Number(amountCentsRaw);
  if (!Number.isInteger(amountCents) || amountCents <= 0) {
    console.error("--amount-cents must be a positive integer");
    process.exit(1);
  }

  const toPubkey = new PublicKey(wallet); // throws on malformed address
  const lamports = BigInt(Math.floor((amountCents * LAMPORTS_PER_SOL) / SOL_PRICE_CENTS));
  if (lamports <= 0n) {
    console.error("Amount too small: converts to 0 lamports");
    process.exit(1);
  }

  const payer = Keypair.fromSecretKey(
    new Uint8Array(JSON.parse(fs.readFileSync(WALLET, "utf-8"))),
  );

  const connection = new Connection(RPC, "confirmed");
  const tx = new Transaction().add(
    SystemProgram.transfer({
      fromPubkey: payer.publicKey,
      toPubkey,
      lamports,
    }),
  );
  const signature = await sendAndConfirmTransaction(connection, tx, [payer]);

  console.log(
    JSON.stringify({
      signature,
      wallet,
      amount_cents: amountCents,
      lamports: lamports.toString(),
    }),
  );
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : String(e));
  process.exit(1);
});
