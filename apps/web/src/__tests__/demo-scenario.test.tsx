// DEMO-ONLY test: safe to delete along with src/features/demo/
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDemoState, sequenceFor } from "@/features/demo/use-demo-state";
import { DEMO_TICK_INTERVAL_MS } from "@/features/demo/meter-sim";
import { DEMO_ADJUSTED_PRICE, DEMO_AI_PRICE } from "@/features/demo/mock-data";

// useDemoState now reads the connected wallet via useWallet() so the seller
// receives the payout in their own account. In tests there's no wallet —
// mock it out and return null so the server action falls back to the default.
vi.mock("@solana/wallet-adapter-react", () => ({
  useWallet: vi.fn(() => ({ publicKey: null, connected: false, sendTransaction: vi.fn() })),
}));

// payment_sending fires a real devnet transfer via this server action; stub it
// with a deterministic confirmed signature so the state machine settles without
// touching the network.
vi.mock("@/app/actions/demo-payout", () => ({
  payDemoSeller: vi.fn(async () => ({
    ok: true,
    signature: "TEST_SIG_11111111111111111111111111111111",
    explorerUrl: "https://explorer.solana.com/tx/TEST_SIG?cluster=devnet",
    operator: "5vPhKdebStaLQ7MS2CLgqo6U5hvppQ222dcG9MEJS89b",
    seller: "3VVoZKsc4HGtrACTGF35jo63wEKojSfQem9yggtXzb6F",
    lamports: 1_000_000,
  })),
}));

afterEach(() => vi.useRealTimers());

/** Drive the scenario to completion, letting the meter accumulate surplus
 *  before submitting. Auto-advance steps are pushed by fake timers. */
async function runToEnd(result: { current: ReturnType<typeof useDemoState> }) {
  // Let the meter tick so there's real surplus to submit (not a literal).
  act(() => vi.advanceTimersByTime(DEMO_TICK_INTERVAL_MS * 8));
  const availableAtSubmit = result.current.meter.availableSurplusKwh;

  // Walk the sequence: click through manual steps, let timers fire the
  // timer-driven auto steps, and flush the promise for payment_sending (which
  // settles via the mocked devnet transfer, not a timer).
  for (let i = 0; i < 12 && !result.current.isFinished; i++) {
    const step = result.current.state.step;
    if (step === "payment_sending") {
      // Flush the resolved payDemoSeller() promise so SETTLE dispatches.
      // eslint-disable-next-line @typescript-eslint/require-await
      await act(async () => {
        await Promise.resolve();
      });
    } else if (["ai_recommending", "operator_reviewing"].includes(step)) {
      act(() => vi.advanceTimersByTime(2000));
    } else {
      act(() => result.current.advance());
    }
  }
  return availableAtSubmit;
}

describe("useDemoState wiring", () => {
  it("surplus figure comes from the live meter, not a hardcoded literal", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDemoState());

    const before = result.current.meter.availableSurplusKwh;
    act(() => vi.advanceTimersByTime(DEMO_TICK_INTERVAL_MS * 5));
    const after = result.current.meter.availableSurplusKwh;

    // Meter accumulated surplus, and the idle step detail reflects it.
    expect(after).toBeGreaterThan(before);
    expect(result.current.stepInfo.detail).toContain(after.toFixed(2));
  });

  it("auto-approve path pays the seller and grows the pool from submitted surplus", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDemoState());

    const submitted = await runToEnd(result);

    expect(result.current.state.step).toBe("payment_confirmed");
    expect(submitted).toBeGreaterThan(0);
    expect(result.current.state.submittedKwh).toBeCloseTo(submitted, 2);
    expect(result.current.state.poolKwh).toBeCloseTo(submitted, 2);
    // Auto case settles at the AI price.
    const expectedPayout = Math.round(submitted * DEMO_AI_PRICE * 100) / 100;
    expect(result.current.state.sellerBalance).toBeCloseTo(expectedPayout, 2);
    expect(result.current.state.operatorBalance).toBeCloseTo(500 - expectedPayout, 2);
  });

  it("operator-review path settles at the adjusted price", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDemoState());

    act(() => result.current.setCase("review"));
    const submitted = await runToEnd(result);

    expect(sequenceFor("review")).toContain("operator_approved");
    expect(result.current.state.step).toBe("payment_confirmed");
    expect(result.current.state.finalPrice).toBe(DEMO_ADJUSTED_PRICE);
    const expectedPayout = Math.round(submitted * DEMO_ADJUSTED_PRICE * 100) / 100;
    expect(result.current.state.sellerBalance).toBeCloseTo(expectedPayout, 2);
  });

  it("reset clears meter surplus, scenario step, wallets and pool", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDemoState());

    await runToEnd(result);
    expect(result.current.state.sellerBalance).toBeGreaterThan(0);

    act(() => result.current.reset());

    expect(result.current.state.step).toBe("idle");
    expect(result.current.state.submittedKwh).toBe(0);
    expect(result.current.state.sellerBalance).toBe(0);
    expect(result.current.state.operatorBalance).toBe(500);
    expect(result.current.state.poolKwh).toBe(0);
    expect(result.current.meter.availableSurplusKwh).toBe(0);
  });

  it("switching role preserves scenario state (same underlying machine)", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDemoState());

    act(() => vi.advanceTimersByTime(DEMO_TICK_INTERVAL_MS * 6));
    act(() => result.current.advance()); // submit
    const submittedKwh = result.current.state.submittedKwh;

    act(() => result.current.setRole("operator"));
    expect(result.current.state.role).toBe("operator");
    // Operator sees the very surplus the seller submitted — not a new mock.
    expect(result.current.state.submittedKwh).toBe(submittedKwh);
  });
});
