/**
 * Phase 8 — one-time Bubblegum merkle tree setup for contribution badges.
 *
 * Creates a compressed-NFT tree on devnet and prints the tree address.
 * Save that address as BADGE_TREE_ADDRESS for the API's BubblegumBadgeMinter.
 *
 * Usage: npx tsx scripts/setup-badge-tree.ts
 *
 * maxDepth 14 / maxBufferSize 64 → 16,384 badge capacity, the smallest
 * canopy-free config Bubblegum supports that comfortably covers a solo
 * community's badge volume. Costs ~0.23 SOL of rent on devnet.
 */
import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import { keypairIdentity, generateSigner } from "@metaplex-foundation/umi";
import { createTree, mplBubblegum } from "@metaplex-foundation/mpl-bubblegum";
import fs from "fs";
import os from "os";
import path from "path";

const RPC = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";
const WALLET = process.env.SOLANA_WALLET ?? path.join(os.homedir(), ".config", "solana", "id.json");

async function main() {
  const umi = createUmi(RPC).use(mplBubblegum());

  const secret = new Uint8Array(JSON.parse(fs.readFileSync(WALLET, "utf-8")));
  const keypair = umi.eddsa.createKeypairFromSecretKey(secret);
  umi.use(keypairIdentity(keypair));

  const merkleTree = generateSigner(umi);

  console.error(`Creating badge tree ${merkleTree.publicKey} with payer ${keypair.publicKey}...`);

  const builder = await createTree(umi, {
    merkleTree,
    maxDepth: 14,
    maxBufferSize: 64,
    // Only the tree creator (the operator wallet) may mint badges
    public: false,
  });
  await builder.sendAndConfirm(umi);

  // Single JSON line on stdout for machine consumption
  console.log(JSON.stringify({ treeAddress: merkleTree.publicKey }));
  console.error(`\nBadge tree created: ${merkleTree.publicKey}`);
  console.error(`Set BADGE_TREE_ADDRESS=${merkleTree.publicKey} for the API.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
