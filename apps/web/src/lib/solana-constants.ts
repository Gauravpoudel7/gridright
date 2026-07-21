/**
 * Shared Solana constants for the web client.
 *
 * PLACEHOLDER: SOL_PRICE_CENTS is a fixed devnet rate (1 SOL = $150), NOT a
 * live price feed. It MUST match `SOL_PRICE_CENTS` in
 * programs/gridright/programs/gridright/src/lib.rs — the on-chain program
 * performs the same cents→lamports conversion and the two must agree.
 * Replace both with an oracle feed in production.
 */
export const SOL_PRICE_CENTS = 15_000;
export const LAMPORTS_PER_SOL = 1_000_000_000;

export function centsToLamports(cents: number): bigint {
  return BigInt(Math.floor((cents * LAMPORTS_PER_SOL) / SOL_PRICE_CENTS));
}
