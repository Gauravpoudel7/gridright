// DEMO-ONLY: safe to delete — remove this file along with src/features/demo/, src/app/demo/, and the "Try the Demo" button on src/app/page.tsx

// Real devnet addresses — the demo settles with a genuine on-chain transfer
// from operator → seller (see src/app/actions/demo-payout.ts). Kept in sync
// with DEMO_OPERATOR_KEYPAIR / DEMO_SELLER_WALLET defaults.
export const MOCK_SELLER_WALLET = "3VVoZKsc4HGtrACTGF35jo63wEKojSfQem9yggtXzb6F";
export const MOCK_OPERATOR_WALLET = "5vPhKdebStaLQ7MS2CLgqo6U5hvppQ222dcG9MEJS89b";

// PLACEHOLDER demo pricing — illustrative only. AI recommends the band price;
// the operator-review case nudges it up to the adjusted price.
export const DEMO_AI_PRICE = 0.115;
export const DEMO_ADJUSTED_PRICE = 0.12;

export type DemoStep =
  | "idle"
  | "surplus_submitted"
  | "ai_recommending"
  | "auto_approved"
  | "flagged_review"
  | "operator_reviewing"
  | "operator_approved"
  | "payment_sending"
  | "payment_confirmed";

export type DemoContribution = {
  id: string;
  kwh: number;
  aiPrice: number;
  finalPrice: number;
  status: string;
  txSignature: string | null;
  case: "auto" | "review";
};

/** Context the step copy is rendered against — all live scenario values, no
 *  hardcoded surplus/price literals. */
export type StepContext = {
  availableKwh: number;
  submittedKwh: number;
  finalPrice: number;
};

/** Label + detail for a step, computed from live scenario state. */
export function describeStep(step: DemoStep, ctx: StepContext): { label: string; detail: string } {
  const kwh = ctx.submittedKwh > 0 ? ctx.submittedKwh : ctx.availableKwh;
  const kwhStr = `${kwh.toFixed(2)} kWh`;
  const price = `$${ctx.finalPrice.toFixed(4)}/kWh`;
  switch (step) {
    case "idle":
      return {
        label: "Ready",
        detail: `Seller has ${ctx.availableKwh.toFixed(2)} kWh surplus available from the meter.`,
      };
    case "surplus_submitted":
      return { label: "Surplus submitted", detail: `Seller submitted ${kwhStr} to the community pool.` };
    case "ai_recommending":
      return { label: "AI recommending…", detail: "AI model analysing pool state and time-of-day pricing." };
    case "auto_approved":
      return { label: "Auto-approved", detail: `Price within policy band — auto-approved at ${price}.` };
    case "flagged_review":
      return { label: "Flagged for review", detail: "Price outside policy band — queued for operator review." };
    case "operator_reviewing":
      return { label: "Operator reviewing…", detail: "Operator examining the exception and deviation reason." };
    case "operator_approved":
      return { label: "Operator approved", detail: `Operator approved at adjusted price ${price}.` };
    case "payment_sending":
      return { label: "Payment sending…", detail: `Sending payout for ${kwhStr} from operator to seller wallet.` };
    case "payment_confirmed":
      return { label: "Payment confirmed ✓", detail: "Transaction confirmed on devnet. Seller balance updated." };
  }
}
