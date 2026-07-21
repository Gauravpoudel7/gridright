import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock wallet adapter
vi.mock("@solana/wallet-adapter-react", () => ({
  useWallet: vi.fn(),
}));

vi.mock("@solana/wallet-adapter-react-ui", () => ({
  WalletMultiButton: () => <button>Connect Wallet</button>,
}));

vi.mock("@/lib/supabase/client", () => ({
  getSupabaseBrowserClient: vi.fn(() => ({
    auth: { getUser: vi.fn().mockResolvedValue({ data: { user: null } }) },
    from: vi.fn(() => ({ update: vi.fn(() => ({ eq: vi.fn() })) })),
  })),
}));

vi.mock("@/hooks/use-realtime-table", () => ({
  useRealtimeTable: vi.fn(() => ({ lastChange: null, live: false })),
}));

vi.mock("@/components/realtime-dashboard", () => ({
  LiveDot: ({ live }: { live: boolean }) => live ? <span>Live</span> : null,
}));

vi.mock("@/hooks/use-pay-seller", () => ({
  usePaySeller: vi.fn(() => ({ pay: vi.fn(), status: "idle", error: null })),
}));

import { useWallet } from "@solana/wallet-adapter-react";
import { OperatorFeedClient } from "@/app/operator/dashboard/operator-feed-client";

const mockFeedItem = {
  id: "contrib-1",
  seller_id: "seller-1",
  kwh_contributed: 100,
  ai_recommended_price: 0.115,
  final_approved_price: 0.115,
  approval_type: "auto",
  approval_reason: null,
  status: "settled",
  direction: "local_pool",
  deviation_reason: null,
  created_at: "2026-01-01T00:00:00Z",
  seller_wallet: "7xKXabc123",
  settlement_pda: "9mPQdef456",
  payout_amount_cents: 1150,
};

describe("OperatorFeedClient — payout gate", () => {
  beforeEach(() => vi.clearAllMocks());

  it("blocks payout when operator wallet not connected and not saved", () => {
    vi.mocked(useWallet).mockReturnValue({
      publicKey: null,
      connected: false,
      sendTransaction: vi.fn(),
    } as never);

    render(<OperatorFeedClient initialFeed={[mockFeedItem]} savedWalletAddress={null} />);
    expect(screen.getByText("Connect operator wallet to pay")).toBeInTheDocument();
  });

  it("shows Pay seller button when wallet is connected", async () => {
    const { PublicKey } = await import("@solana/web3.js");
    vi.mocked(useWallet).mockReturnValue({
      publicKey: new PublicKey("11111111111111111111111111111111"),
      connected: true,
      sendTransaction: vi.fn(),
    } as never);

    render(<OperatorFeedClient initialFeed={[mockFeedItem]} savedWalletAddress={null} />);
    expect(screen.getByText("Pay seller")).toBeInTheDocument();
  });

  it("shows Pay seller button when wallet address is saved (not connected)", () => {
    vi.mocked(useWallet).mockReturnValue({
      publicKey: null,
      connected: false,
      sendTransaction: vi.fn(),
    } as never);

    render(
      <OperatorFeedClient
        initialFeed={[mockFeedItem]}
        savedWalletAddress="11111111111111111111111111111111"
      />,
    );
    expect(screen.getByText("Pay seller")).toBeInTheDocument();
  });
});
