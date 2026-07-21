import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { mockOperatorUser, mockSellerUser, mockSession, jsonResponse, RedirectError } from "./test-utils";

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

vi.mock("@/hooks/use-pay-seller", () => ({
  usePaySeller: vi.fn(() => ({ pay: vi.fn(), status: "idle", error: null })),
}));

vi.mock("@/components/realtime-dashboard", () => ({
  LiveDot: () => null,
  useRealtimeHistory: vi.fn((initial: unknown[]) => ({ history: initial, live: false })),
  useRealtimeDashboard: vi.fn((initial: unknown) => ({ data: initial, live: false })),
}));

import { getCurrentUser } from "@/lib/supabase/get-current-user";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import OperatorDashboardPage from "@/app/operator/dashboard/page";

const mockFeed = [
  {
    id: "feed-1",
    seller_id: "seller-1",
    kwh_contributed: 150,
    ai_recommended_price: 0.12,
    final_approved_price: 0.12,
    approval_type: "auto",
    approval_reason: null,
    status: "settled",
    direction: "local_pool",
    deviation_reason: null,
    created_at: "2026-01-15T10:00:00Z",
  },
  {
    id: "feed-2",
    seller_id: "seller-2",
    kwh_contributed: 200,
    ai_recommended_price: 0.15,
    final_approved_price: 0.14,
    approval_type: "human",
    approval_reason: "Operator adjustment",
    status: "settled",
    direction: "export",
    deviation_reason: null,
    created_at: "2026-01-15T11:00:00Z",
  },
];

const mockPendingReviews = [
  {
    id: "review-1",
    kwh_contributed: 100,
    ai_recommended_price: 0.18,
    recommended_absorption_kwh: 80,
    deviation_reason: "Price exceeds upper band by 15%",
    created_at: "2026-01-15T09:00:00Z",
    direction: "local_pool",
  },
  {
    id: "review-2",
    kwh_contributed: 75,
    ai_recommended_price: 0.05,
    recommended_absorption_kwh: 75,
    deviation_reason: "Price below lower band",
    created_at: "2026-01-15T08:30:00Z",
    direction: "local_pool",
  },
  {
    id: "review-3",
    kwh_contributed: 50,
    ai_recommended_price: 0.25,
    recommended_absorption_kwh: 50,
    deviation_reason: "Import price outside band",
    created_at: "2026-01-15T07:00:00Z",
    direction: "import",
  },
];

const mockPool = {
  total_kwh_contributed: 5000,
  current_absorption_kwh: 3200,
  absorption_limit_kwh: 4500,
  pending_import_export: [
    {
      id: "ie-1",
      seller_id: "seller-1",
      kwh: 500,
      ai_recommended_price: 0.10,
      direction: "import",
      deviation_reason: null,
      created_at: "2026-01-15T12:00:00Z",
    },
    {
      id: "ie-2",
      seller_id: "seller-2",
      kwh: 300,
      ai_recommended_price: 0.08,
      direction: "export",
      deviation_reason: "Grid demand low",
      created_at: "2026-01-15T13:00:00Z",
    },
  ],
};

const mockDistribution = [
  { seller_id: "seller-abc", total_kwh: 1500, contribution_count: 12 },
  { seller_id: "seller-def", total_kwh: 980, contribution_count: 8 },
];

const mockStats = {
  total_kwh_settled: 12500,
  total_payouts: 1875.5,
  total_spread_captured: 312.25,
  average_uplift_percentage: 8.5,
  feed_in_tariff_reference: 0.08,
  settled_count: 42,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", vi.fn());
});

async function setupMocks(user: ReturnType<typeof mockOperatorUser> | ReturnType<typeof mockSellerUser> | null) {
  vi.mocked(getCurrentUser).mockResolvedValue(user as never);

  const walletChain = { eq: vi.fn(() => ({ single: vi.fn().mockResolvedValue({ data: { wallet_address: null }, error: null }) })) };
  const mockSupabase = {
    auth: { getSession: vi.fn().mockResolvedValue(mockSession()) },
    from: vi.fn(() => ({ select: vi.fn(() => walletChain) })),
  };
  vi.mocked(createSupabaseServerClient).mockResolvedValue(mockSupabase as never);

  vi.mocked(fetch).mockImplementation((url: string) => {
    if (url.includes("/operator/feed")) return Promise.resolve(jsonResponse(mockFeed));
    if (url.includes("/reviews/pending")) return Promise.resolve(jsonResponse(mockPendingReviews));
    if (url.includes("/operator/pool")) return Promise.resolve(jsonResponse(mockPool));
    if (url.includes("/operator/distribution")) return Promise.resolve(jsonResponse(mockDistribution));
    if (url.includes("/operator/stats")) return Promise.resolve(jsonResponse(mockStats));
    return Promise.resolve(new Response("{}", { status: 404 }));
  });
}

describe("OperatorDashboardPage", () => {
  it("redirects to /operator/login when no user", async () => {
    await setupMocks(null);
    await expect(OperatorDashboardPage()).rejects.toThrow(RedirectError);
    try {
      await OperatorDashboardPage();
    } catch (e: unknown) {
      if (e instanceof RedirectError) expect(e.url).toBe("/operator/login");
    }
  });

  it("redirects non-operator roles", async () => {
    await setupMocks(mockSellerUser());
    await expect(OperatorDashboardPage()).rejects.toThrow(RedirectError);
    try {
      await OperatorDashboardPage();
    } catch (e: unknown) {
      if (e instanceof RedirectError) expect(e.url).toBe("/login?error=not_operator");
    }
  });

  it("renders aggregate stat cards", async () => {
    await setupMocks(mockOperatorUser());
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText("$312.25")).toBeInTheDocument();
    expect(screen.getByText("8.50")).toBeInTheDocument();
    expect(screen.getByText("12500.00")).toBeInTheDocument();
    expect(screen.getByText("$1875.50")).toBeInTheDocument();
    expect(screen.getByText("Total spread captured")).toBeInTheDocument();
    expect(screen.getByText("Avg seller uplift over tariff")).toBeInTheDocument();
    expect(screen.getByText("Settled energy")).toBeInTheDocument();
    expect(screen.getByText("Total payouts")).toBeInTheDocument();
  });

  it("exception queue shows only local_pool reviews", async () => {
    await setupMocks(mockOperatorUser());
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText("Exception queue")).toBeInTheDocument();
    // local_pool reviews
    expect(screen.getByText(/Price exceeds upper band by 15%/)).toBeInTheDocument();
    expect(screen.getByText(/Price below lower band/)).toBeInTheDocument();
    // import-direction review should NOT appear in the exception queue
    expect(screen.queryByText(/Import price outside band/)).not.toBeInTheDocument();
  });

  it("import/export panel shows pending pool items", async () => {
    await setupMocks(mockOperatorUser());
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText("Import / export")).toBeInTheDocument();
    expect(screen.getByText(/500\.00 kWh/)).toBeInTheDocument();
    expect(screen.getByText(/300\.00 kWh/)).toBeInTheDocument();
    expect(screen.getByText("Grid demand low")).toBeInTheDocument();
  });

  it("import/export panel shows pool stat cards", async () => {
    await setupMocks(mockOperatorUser());
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText("5000.00")).toBeInTheDocument();
    expect(screen.getByText("3200.00")).toBeInTheDocument();
    expect(screen.getByText("4500.00")).toBeInTheDocument();
  });

  it("distribution table renders seller data", async () => {
    await setupMocks(mockOperatorUser());
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText("seller-abc")).toBeInTheDocument();
    expect(screen.getByText("seller-def")).toBeInTheDocument();
    expect(screen.getByText("1500.00")).toBeInTheDocument();
    expect(screen.getByText("980.00")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
  });

  it("recommendation feed shows items with status badges", async () => {
    await setupMocks(mockOperatorUser());
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText("Recommendation feed")).toBeInTheDocument();
    expect(screen.getByText("auto-approved")).toBeInTheDocument();
    expect(screen.getByText("human decision")).toBeInTheDocument();
    expect(screen.getByText("Reason: Operator adjustment")).toBeInTheDocument();
  });

  it("shows empty state for empty feed", async () => {
    await setupMocks(mockOperatorUser());
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (url.includes("/operator/feed")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/reviews/pending")) return Promise.resolve(jsonResponse(mockPendingReviews));
      if (url.includes("/operator/pool")) return Promise.resolve(jsonResponse(mockPool));
      if (url.includes("/operator/distribution")) return Promise.resolve(jsonResponse(mockDistribution));
      if (url.includes("/operator/stats")) return Promise.resolve(jsonResponse(mockStats));
      return Promise.resolve(new Response("{}", { status: 404 }));
    });
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText("No recommendations yet.")).toBeInTheDocument();
  });

  it("shows empty state when no pending exceptions", async () => {
    await setupMocks(mockOperatorUser());
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (url.includes("/operator/feed")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/reviews/pending")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/operator/pool")) return Promise.resolve(jsonResponse(mockPool));
      if (url.includes("/operator/distribution")) return Promise.resolve(jsonResponse(mockDistribution));
      if (url.includes("/operator/stats")) return Promise.resolve(jsonResponse(mockStats));
      return Promise.resolve(new Response("{}", { status: 404 }));
    });
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText(/No pending exceptions/)).toBeInTheDocument();
  });

  it("shows empty state when no import/export pending", async () => {
    await setupMocks(mockOperatorUser());
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (url.includes("/operator/feed")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/reviews/pending")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/operator/pool")) return Promise.resolve(jsonResponse({ ...mockPool, pending_import_export: [] }));
      if (url.includes("/operator/distribution")) return Promise.resolve(jsonResponse(mockDistribution));
      if (url.includes("/operator/stats")) return Promise.resolve(jsonResponse(mockStats));
      return Promise.resolve(new Response("{}", { status: 404 }));
    });
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText(/No pending import or export recommendations/)).toBeInTheDocument();
  });

  it("shows empty distribution state", async () => {
    await setupMocks(mockOperatorUser());
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (url.includes("/operator/feed")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/reviews/pending")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/operator/pool")) return Promise.resolve(jsonResponse(mockPool));
      if (url.includes("/operator/distribution")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/operator/stats")) return Promise.resolve(jsonResponse(mockStats));
      return Promise.resolve(new Response("{}", { status: 404 }));
    });
    const element = await OperatorDashboardPage();
    render(element);

    expect(screen.getByText("No contributions yet.")).toBeInTheDocument();
  });
});
