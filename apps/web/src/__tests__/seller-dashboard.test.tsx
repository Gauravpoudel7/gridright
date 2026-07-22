import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { mockSellerUser, mockSession, jsonResponse, RedirectError } from "./test-utils";

vi.mock("@/lib/supabase/get-current-user", () => ({
  getCurrentUser: vi.fn(),
}));

vi.mock("@/lib/supabase/server", () => ({
  createSupabaseServerClient: vi.fn(),
}));

vi.mock("@solana/wallet-adapter-react", () => ({
  useWallet: vi.fn(() => ({ publicKey: null, connected: false, sendTransaction: vi.fn() })),
}));

vi.mock("@solana/wallet-adapter-react-ui", () => ({
  WalletMultiButton: () => null,
}));

vi.mock("@/lib/supabase/client", () => ({
  getSupabaseBrowserClient: vi.fn(() => ({
    auth: { getUser: vi.fn().mockResolvedValue({ data: { user: null } }) },
    from: vi.fn(() => ({ update: vi.fn(() => ({ eq: vi.fn() })) })),
    channel: vi.fn(() => ({ on: vi.fn(() => ({ subscribe: vi.fn() })), subscribe: vi.fn() })),
    removeChannel: vi.fn(),
  })),
}));

vi.mock("@/hooks/use-realtime-table", () => ({
  useRealtimeTable: vi.fn(() => ({ lastChange: null, live: false })),
}));

vi.mock("@/components/realtime-dashboard", () => ({
  LiveDot: () => null,
  useRealtimeHistory: vi.fn((initial: unknown[]) => ({ history: initial, live: false })),
  useRealtimeDashboard: vi.fn((initial: unknown) => ({ data: initial, live: false })),
}));

import { getCurrentUser } from "@/lib/supabase/get-current-user";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import SellerDashboardPage from "@/app/dashboard/page";

const mockDashboardData = {
  surplus_this_period: 120.5,
  cumulative_kwh: 2340.0,
  total_earned: 456.78,
  period_start: "2026-01-01",
  period_end: "2026-01-31",
};

const mockHistory = [
  {
    period_start: "2025-12-01T00:00:00Z",
    period_end: "2025-12-31T00:00:00Z",
    kwh_contributed: 300.5,
    amount_earned: 45.08,
    status: "settled",
  },
  {
    period_start: "2025-11-01T00:00:00Z",
    period_end: "2025-11-30T00:00:00Z",
    kwh_contributed: 250.0,
    amount_earned: 37.5,
    status: "needs_review",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", vi.fn());
});

async function setupMocks(
  user: ReturnType<typeof mockSellerUser> | null,
  dashboardData = mockDashboardData,
  history = mockHistory,
) {
  const mockGetCurrentUser = vi.mocked(getCurrentUser);
  mockGetCurrentUser.mockResolvedValue(user);

  const mockCreateClient = vi.mocked(createSupabaseServerClient);
  const walletChain = { eq: vi.fn(() => ({ single: vi.fn().mockResolvedValue({ data: { wallet_address: null }, error: null }) })) };
  const mockSupabase = {
    auth: { getSession: vi.fn().mockResolvedValue(mockSession()) },
    from: vi.fn(() => ({ select: vi.fn(() => walletChain) })),
  };
  mockCreateClient.mockResolvedValue(mockSupabase as never);

  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("dashboard")) return Promise.resolve(jsonResponse(dashboardData));
    if (url.includes("history")) return Promise.resolve(jsonResponse(history));
    return Promise.resolve(new Response("{}", { status: 404 }));
  });
}

describe("SellerDashboardPage", () => {
  it("redirects to /login when no user", async () => {
    await setupMocks(null);
    await expect(SellerDashboardPage()).rejects.toThrow(RedirectError);
    try {
      await SellerDashboardPage();
    } catch (e: unknown) {
      if (e instanceof RedirectError) {
        expect(e.url).toBe("/login");
      }
    }
  });

  it("redirects non-seller roles", async () => {
    const opUser = { id: "op-1", email: "op@grid.com", role: "operator" as const };
    await setupMocks(opUser);
    const pagePromise = SellerDashboardPage();
    await expect(pagePromise).rejects.toThrow(RedirectError);
    try {
      await pagePromise;
    } catch (e: unknown) {
      if (e instanceof RedirectError) {
        expect(e.url).toBe("/operator/login?error=not_seller");
      }
    }
  });

  it("renders stat cards with correct values", async () => {
    await setupMocks(mockSellerUser());
    const element = await SellerDashboardPage();
    render(element);

    expect(screen.getByText("120.50")).toBeInTheDocument();
    expect(screen.getByText("2340.00")).toBeInTheDocument();
    expect(screen.getByText("456.78")).toBeInTheDocument();
    expect(screen.getByText("Surplus this period")).toBeInTheDocument();
    expect(screen.getByText("Cumulative contributed")).toBeInTheDocument();
    expect(screen.getByText("Total earned")).toBeInTheDocument();
  });

  it("shows only the payout wallet section — legacy Phantom row is gone", async () => {
    await setupMocks(mockSellerUser());
    const element = await SellerDashboardPage();
    render(element);

    // The signed-challenge payout wallet (WalletActivate) is the single
    // wallet UI; the old unverified "Phantom wallet" row was removed.
    expect(screen.getByText("Payout wallet")).toBeInTheDocument();
    expect(screen.queryByText("Phantom wallet")).not.toBeInTheDocument();
    expect(screen.queryByText(/connect a wallet to list surplus/i)).not.toBeInTheDocument();
  });

  it("renders history table rows", async () => {
    await setupMocks(mockSellerUser());
    const element = await SellerDashboardPage();
    render(element);

    expect(screen.getByText("settled")).toBeInTheDocument();
    expect(screen.getByText("needs review")).toBeInTheDocument();
    expect(screen.getByText("300.50")).toBeInTheDocument();
    expect(screen.getByText("250.00")).toBeInTheDocument();
  });

  it("renders settled amount with dollar sign", async () => {
    await setupMocks(mockSellerUser());
    const element = await SellerDashboardPage();
    render(element);

    expect(screen.getByText("$45.08")).toBeInTheDocument();
    // needs_review shows em-dash, not dollar amount
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows empty state when history is empty", async () => {
    await setupMocks(mockSellerUser(), mockDashboardData, []);
    const element = await SellerDashboardPage();
    render(element);

    expect(screen.getByText("No contributions yet.")).toBeInTheDocument();
  });

  it("renders CSV export link pointing to the right endpoint", async () => {
    await setupMocks(mockSellerUser());
    const element = await SellerDashboardPage();
    render(element);

    const link = screen.getByText("Export CSV");
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/v1/sellers/me/history/export",
    );
  });

  it("shows default zeros when fetch returns no token", async () => {
    const mockCreateClient = vi.mocked(createSupabaseServerClient);
    const walletChain1 = { eq: vi.fn(() => ({ single: vi.fn().mockResolvedValue({ data: { wallet_address: null }, error: null }) })) };
    const mockSupabase = {
      auth: { getSession: vi.fn().mockResolvedValue({ data: { session: null }, error: null }) },
      from: vi.fn(() => ({ select: vi.fn(() => walletChain1) })),
    };
    mockCreateClient.mockResolvedValue(mockSupabase as never);
    const mockGetCurrentUser = vi.mocked(getCurrentUser);
    mockGetCurrentUser.mockResolvedValue(mockSellerUser());

    const element = await SellerDashboardPage();
    render(element);

    expect(screen.getAllByText("0.00")).toHaveLength(3);
  });

  it("survives no token gracefully but empty history does not crash", async () => {
    const mockCreateClient = vi.mocked(createSupabaseServerClient);
    const walletChain2 = { eq: vi.fn(() => ({ single: vi.fn().mockResolvedValue({ data: { wallet_address: null }, error: null }) })) };
    const mockSupabase = {
      auth: { getSession: vi.fn().mockResolvedValue(mockSession()) },
      from: vi.fn(() => ({ select: vi.fn(() => walletChain2) })),
    };
    mockCreateClient.mockResolvedValue(mockSupabase as never);
    const mockGetCurrentUser = vi.mocked(getCurrentUser);
    mockGetCurrentUser.mockResolvedValue(mockSellerUser());

    vi.mocked(fetch).mockImplementation((url: string) => {
      if (url.includes("dashboard")) return Promise.resolve(jsonResponse(mockDashboardData));
      if (url.includes("history")) return Promise.resolve(jsonResponse([]));
      return Promise.resolve(new Response("{}", { status: 404 }));
    });

    const element = await SellerDashboardPage();
    render(element);

    expect(screen.getByText("120.50")).toBeInTheDocument();
    expect(screen.getByText("No contributions yet.")).toBeInTheDocument();
  });
});
