/**
 * Phase 8 — mint one contribution-milestone badge cNFT.
 *
 * Called by the API's BubblegumBadgeMinter (badge_service.py) when a
 * seller's cumulative settled kWh crosses a threshold. Prints a single
 * JSON line: {"assetId": "...", "signature": "..."}.
 *
 * Usage:
 *   npx tsx scripts/mint-badge.ts \
 *     --tree <BADGE_TREE_ADDRESS> \
 *     --seller <seller uuid> \
 *     --label "Community Contributor — 100 kWh" \
 *     --threshold 100 \
 *     [--owner <solana pubkey>]        # defaults to the operator wallet
 *
 * Sellers are identified by Supabase uuid, not a wallet — badges are minted
 * to the operator wallet (custodial) with the seller uuid and threshold in
 * the metadata attributes, transferable to a seller wallet later.
 */
import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import { keypairIdentity, publicKey } from "@metaplex-foundation/umi";
import {
  findLeafAssetIdPda,
  mintV1,
  mplBubblegum,
  parseLeafFromMintV1Transaction,
} from "@metaplex-foundation/mpl-bubblegum";
import { base58 } from "@metaplex-foundation/umi/serializers";
import fs from "fs";
import os from "os";
import path from "path";

const RPC = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";
const WALLET = process.env.SOLANA_WALLET ?? path.join(os.homedir(), ".config", "solana", "id.json");

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

/** Bubblegum's 32-char name limit is measured in UTF-8 bytes, not JS chars —
 * labels with em-dashes etc. must be truncated by bytes on a char boundary. */
function truncateUtf8(s: string, maxBytes: number): string {
  const enc = new TextEncoder();
  while (enc.encode(s).length > maxBytes) s = s.slice(0, -1);
  return s;
}

async function main() {
  const tree = arg("tree") ?? process.env.BADGE_TREE_ADDRESS;
  const seller = arg("seller");
  const label = arg("label");
  const threshold = arg("threshold");
  if (!tree || !seller || !label || !threshold) {
    console.error("Required: --tree, --seller, --label, --threshold");
    process.exit(1);
  }

  const umi = createUmi(RPC).use(mplBubblegum());
  const secret = new Uint8Array(JSON.parse(fs.readFileSync(WALLET, "utf-8")));
  umi.use(keypairIdentity(umi.eddsa.createKeypairFromSecretKey(secret)));

  const merkleTree = publicKey(tree);
  const owner = arg("owner") ? publicKey(arg("owner")!) : umi.identity.publicKey;

  const { signature } = await mintV1(umi, {
    leafOwner: owner,
    merkleTree,
    metadata: {
      name: truncateUtf8(label, 32), // Bubblegum limit is 32 UTF-8 bytes
      // Off-chain JSON is out of scope for v1 — attributes live in the
      // Supabase seller_badges row; uri left empty intentionally.
      uri: "",
      sellerFeeBasisPoints: 0,
      collection: { key: publicKey("11111111111111111111111111111111"), verified: false },
      creators: [{ address: umi.identity.publicKey, verified: true, share: 100 }],
    },
  }).sendAndConfirm(umi, { confirm: { commitment: "confirmed" } });

  // parseLeafFromMintV1Transaction fetches at finalized commitment; the tx
  // just confirmed, so retry until it's queryable.
  let leaf;
  for (let attempt = 0; ; attempt++) {
    try {
      leaf = await parseLeafFromMintV1Transaction(umi, signature);
      break;
    } catch (err) {
      if (attempt >= 15) throw err;
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  const [assetId] = findLeafAssetIdPda(umi, { merkleTree, leafIndex: leaf.nonce });

  console.log(
    JSON.stringify({
      assetId: assetId.toString(),
      signature: base58.deserialize(signature)[0],
      seller,
      threshold: Number(threshold),
    }),
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
