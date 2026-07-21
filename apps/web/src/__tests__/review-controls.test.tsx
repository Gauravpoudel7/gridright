import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/app/actions/operator", () => ({
  resolveReviewAction: vi.fn(),
}));

import { resolveReviewAction } from "@/app/actions/operator";
import { ReviewControls } from "@/app/operator/dashboard/review-controls";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(resolveReviewAction).mockResolvedValue({ ok: true });
});

describe("ReviewControls", () => {
  it("renders approve/adjust/reject buttons initially", () => {
    render(<ReviewControls reviewId="review-1" />);

    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(screen.getByText("Adjust")).toBeInTheDocument();
    expect(screen.getByText("Reject")).toBeInTheDocument();
  });

  it("shows form with reason and confirm button when Approve is clicked", async () => {
    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-1" />);

    await user.click(screen.getByText("Approve"));

    expect(screen.getByText("Confirm approve")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Why approve?")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
    expect(screen.queryByText("Adjust")).not.toBeInTheDocument();
  });

  it("shows price field when Adjust is clicked", async () => {
    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-1" />);

    await user.click(screen.getByText("Adjust"));

    expect(screen.getByText("Confirm adjust")).toBeInTheDocument();
    expect(screen.getByText("Adjusted price ($/kWh)")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Why adjust?")).toBeInTheDocument();
  });

  it("shows form with reason when Reject is clicked", async () => {
    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-1" />);

    await user.click(screen.getByText("Reject"));

    expect(screen.getByText("Confirm reject")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Why reject?")).toBeInTheDocument();
    expect(screen.queryByText("Adjusted price ($/kWh)")).not.toBeInTheDocument();
  });

  it("returns to initial state on Cancel", async () => {
    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-1" />);

    await user.click(screen.getByText("Approve"));
    await user.click(screen.getByText("Cancel"));

    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(screen.getByText("Adjust")).toBeInTheDocument();
    expect(screen.getByText("Reject")).toBeInTheDocument();
    expect(screen.queryByText("Confirm approve")).not.toBeInTheDocument();
  });

  it("approve calls resolveReviewAction with correct payload", async () => {
    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-123" />);

    await user.click(screen.getByText("Approve"));
    await user.type(screen.getByPlaceholderText("Why approve?"), "Within acceptable range");
    await user.click(screen.getByText("Confirm approve"));

    expect(vi.mocked(resolveReviewAction)).toHaveBeenCalledTimes(1);

    const formData = vi.mocked(resolveReviewAction).mock.calls[0][0];
    expect(formData.get("review_id")).toBe("review-123");
    expect(formData.get("action")).toBe("approve");
    expect(formData.get("reason")).toBe("Within acceptable range");
  });

  it("adjust calls resolveReviewAction with price and reason", async () => {
    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-456" />);

    await user.click(screen.getByText("Adjust"));
    await user.type(screen.getByPlaceholderText("Why adjust?"), "Market rate changed");
    const priceInput = screen.getByLabelText(/Adjusted price/);
    await user.clear(priceInput);
    await user.type(priceInput, "0.095");
    await user.click(screen.getByText("Confirm adjust"));

    expect(vi.mocked(resolveReviewAction)).toHaveBeenCalledTimes(1);

    const formData = vi.mocked(resolveReviewAction).mock.calls[0][0];
    expect(formData.get("review_id")).toBe("review-456");
    expect(formData.get("action")).toBe("adjust");
    expect(formData.get("adjusted_price")).toBe("0.095");
    expect(formData.get("reason")).toBe("Market rate changed");
  });

  it("reject calls resolveReviewAction with reason", async () => {
    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-789" />);

    await user.click(screen.getByText("Reject"));
    await user.type(screen.getByPlaceholderText("Why reject?"), "Price manipulation detected");
    await user.click(screen.getByText("Confirm reject"));

    expect(vi.mocked(resolveReviewAction)).toHaveBeenCalledTimes(1);

    const formData = vi.mocked(resolveReviewAction).mock.calls[0][0];
    expect(formData.get("review_id")).toBe("review-789");
    expect(formData.get("action")).toBe("reject");
    expect(formData.get("reason")).toBe("Price manipulation detected");
  });

  it("displays error message when resolveReviewAction fails", async () => {
    vi.mocked(resolveReviewAction).mockResolvedValue({
      ok: false,
      error: "Server rejected the decision",
    });

    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-1" />);

    await user.click(screen.getByText("Approve"));
    await user.type(screen.getByPlaceholderText("Why approve?"), "OK");
    await user.click(screen.getByText("Confirm approve"));

    expect(await screen.findByText("Server rejected the decision")).toBeInTheDocument();
  });

  it("disables submit button while pending", async () => {
    let resolvePromise: (v: unknown) => void;
    const pendingPromise = new Promise((resolve) => { resolvePromise = resolve; });
    vi.mocked(resolveReviewAction).mockReturnValue(pendingPromise as never);

    const user = userEvent.setup();
    render(<ReviewControls reviewId="review-1" />);

    await user.click(screen.getByText("Approve"));
    await user.type(screen.getByPlaceholderText("Why approve?"), "OK");
    await user.click(screen.getByText("Confirm approve"));

    expect(screen.getByText("Submitting...")).toBeInTheDocument();
    expect(screen.getByText("Submitting...")).toBeDisabled();

    resolvePromise!({ ok: true });
  });

  it("resolveReviewAction itself rejects adjust and reject without a reason", async () => {
    // The top-level vi.mock replaces the action; pull in the real one to
    // exercise its server-side validation directly.
    const { resolveReviewAction: realResolveReviewAction } = await vi.importActual<
      typeof import("@/app/actions/operator")
    >("@/app/actions/operator");

    for (const action of ["adjust", "reject"] as const) {
      // Missing reason field entirely
      const missing = new FormData();
      missing.set("review_id", "review-1");
      missing.set("action", action);
      if (action === "adjust") missing.set("adjusted_price", "0.095");

      const missingResult = await realResolveReviewAction(missing);
      expect(missingResult.ok).toBe(false);
      expect(missingResult.error).toBe("A reason is required for every decision");

      // Present but empty/whitespace-only reason
      const empty = new FormData();
      empty.set("review_id", "review-1");
      empty.set("action", action);
      empty.set("reason", "   ");
      if (action === "adjust") empty.set("adjusted_price", "0.095");

      const emptyResult = await realResolveReviewAction(empty);
      expect(emptyResult.ok).toBe(false);
      expect(emptyResult.error).toBe("A reason is required for every decision");
    }
  });
});
