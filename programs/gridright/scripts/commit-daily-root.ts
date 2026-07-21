/**
 * Phase 5 — commit the daily Merkle root of decision hashes to devnet.
 *
 * Called by the backend daily-commit job (apps/api POST /commitments/run)
 * after sorting all decision_hashes decided within one UTC day and
 * folding them into a single 32-byte root. Prints a single JSON line:
 *   {"signature": "...", "pda": "...", "date": "YYYY-MM-DD",
 *    "merkle_root": "<hex>", "record_count": N}
 *
 * The on-chain account is the source of truth for the day's commitment;
 * the backend stores the same fields in `daily_commitments` as a mirror
 * for explorer-link convenience and for verify without an RPC round-trip.
 *
 * Usage:
 *   npx tsx scripts/commit-daily-root.ts \
 *     --date 2026-07-21 \
 *     --root <64-char hex merkle root> \
 *     --count 42
 */
import * as anchor from "@coral-xyz/anchor";
import fs from "fs";
import os from "os";
import path from "path";

const RPC = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";
const WALLET = process.env.SOLANA_WALLET ?? path.join(os.homedir(), ".config", "solana", "id.json");

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

function hexToBytes(hex: string): number[] {
  if (hex.length !== 64) {
    throw new Error(`--root must be 64 hex chars, got ${hex.length}`);
  }
  if (!/^[0-9a-fA-F]{64}$/.test(hex)) {
    throw new Error("--root contains non-hex characters");
  }
  const out: number[] = [];
  for (let i = 0; i < 64; i += 2) {
    out.push(parseInt(hex.slice(i, i + 2), 16));
  }
  return out;
}

async function main() {
  const date = arg("date");
  const root = arg("root");
  const count = arg("count");
  if (!date || !root || !count) {
    console.error("Required: --date YYYY-MM-DD, --root <hex64>, --count N");
    process.exit(1);
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    console.error("--date must match YYYY-MM-DD");
    process.exit(1);
  }
  const recordCount = Number(count);
  if (!Number.isInteger(recordCount) || recordCount <= 0) {
    console.error("--count must be a positive integer");
    process.exit(1);
  }

  const secret = new Uint8Array(JSON.parse(fs.readFileSync(WALLET, "utf-8")));
  const keypair = anchor.web3.Keypair.fromSecretKey(secret);
  const connection = new anchor.web3.Connection(RPC, "confirmed");
  const provider = new anchor.AnchorProvider(connection, new anchor.Wallet(keypair), {
    commitment: "confirmed",
  });

  const idl = JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "target", "idl", "gridright.json"), "utf-8"),
  );
  const program = new anchor.Program(idl, provider);

  const merkleRoot = hexToBytes(root);

  const [pda] = anchor.web3.PublicKey.findProgramAddressSync(
    [
      Buffer.from("daily_commitment"),
      keypair.publicKey.toBuffer(),
      Buffer.from(date, "utf-8"),
    ],
    program.programId,
  );

  const signature = await program.methods
    .commitDailyRoot(date, merkleRoot, recordCount)
    .accounts({ commitment: pda, authority: keypair.publicKey })
    .rpc();

  // Read back so the caller can assert round-trip state
  const commitment = await (program.account as any).dailyCommitment.fetch(pda);

  console.log(
    JSON.stringify({
      signature,
      pda: pda.toBase58(),
      date: commitment.date,
      merkle_root: Buffer.from(commitment.merkleRoot).toString("hex"),
      record_count: commitment.recordCount,
    }),
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
