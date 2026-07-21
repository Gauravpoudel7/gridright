/**
 * Phase 9 — submit one settle_period transaction to devnet.
 *
 * Called by the E2E regression suite (apps/api/tests/test_e2e_devnet.py) to
 * settle a contribution on-chain. Prints a single JSON line:
 *   {"signature": "...", "pda": "...", "kwh": ..., "direction": "..."}
 *
 * Usage:
 *   npx tsx scripts/settle-period.ts \
 *     --kwh 50000 --price 10 --payout 50000 \
 *     --direction local_pool|import|export \
 *     --record '<full off-chain JSON to hash on-chain>' \
 *     [--period-start <unix seconds>]     # defaults to now (unique per run)
 */
import * as anchor from "@coral-xyz/anchor";
import crypto from "crypto";
import fs from "fs";
import os from "os";
import path from "path";

const RPC = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";
const WALLET = process.env.SOLANA_WALLET ?? path.join(os.homedir(), ".config", "solana", "id.json");

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

async function main() {
  const kwh = arg("kwh");
  const price = arg("price");
  const payout = arg("payout");
  const direction = arg("direction") ?? "local_pool";
  const record = arg("record") ?? "{}";
  if (!kwh || !price || !payout) {
    console.error("Required: --kwh, --price, --payout");
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

  const ps = new anchor.BN(arg("period-start") ?? Math.floor(Date.now() / 1000));
  const ts = new anchor.BN(Date.now()).mul(new anchor.BN(1_000_000));
  const hash = Array.from(crypto.createHash("sha256").update(record).digest());

  const directionArg =
    direction === "import" ? { import: {} } : direction === "export" ? { export: {} } : { localPool: {} };

  const [pda] = anchor.web3.PublicKey.findProgramAddressSync(
    [
      Buffer.from("settlement"),
      keypair.publicKey.toBuffer(),
      new Uint8Array(ps.toArrayLike(Buffer, "le", 8)),
    ],
    program.programId,
  );

  const signature = await program.methods
    .settlePeriod(new anchor.BN(kwh), new anchor.BN(price), new anchor.BN(payout), ps, ts, hash, directionArg)
    .accounts({ settlement: pda, seller: keypair.publicKey })
    .rpc();

  // Read back the on-chain account so the caller can assert round-trip state
  const settlement = await (program.account as any).settlement.fetch(pda);

  console.log(
    JSON.stringify({
      signature,
      pda: pda.toBase58(),
      kwh: settlement.kwhContributed.toNumber(),
      price: settlement.finalApprovedPrice.toNumber(),
      payout: settlement.payoutAmount.toNumber(),
      direction: Object.keys(settlement.direction)[0],
    }),
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
