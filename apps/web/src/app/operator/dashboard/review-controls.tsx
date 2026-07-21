"use client";

import { useState, useTransition } from "react";

import { resolveReviewAction } from "@/app/actions/operator";

type ReviewAction = "approve" | "adjust" | "reject";

/**
 * Approve / adjust / reject controls for a single pending review.
 * A reason is required for every decision; adjust additionally requires
 * a price. Submission goes through the resolveReviewAction server action,
 * which revalidates the dashboard on success.
 */
export function ReviewControls({ reviewId }: { reviewId: string }) {
  const [action, setAction] = useState<ReviewAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (action === null) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setAction("approve")}
          className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
        >
          Approve
        </button>
        <button
          type="button"
          onClick={() => setAction("adjust")}
          className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700"
        >
          Adjust
        </button>
        <button
          type="button"
          onClick={() => setAction("reject")}
          className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
        >
          Reject
        </button>
      </div>
    );
  }

  const submit = (formData: FormData) => {
    setError(null);
    startTransition(async () => {
      const result = await resolveReviewAction(formData);
      if (!result.ok) {
        setError(result.error ?? "Something went wrong");
      }
      // On success the server action revalidates the page and the review
      // disappears from the queue — no local state to clean up.
    });
  };

  return (
    <form action={submit} className="flex flex-col gap-2">
      <input type="hidden" name="review_id" value={reviewId} />
      <input type="hidden" name="action" value={action} />

      {action === "adjust" && (
        <label className="flex flex-col gap-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
          Adjusted price ($/kWh)
          <input
            name="adjusted_price"
            type="number"
            step="0.000001"
            min="0"
            required
            className="h-9 w-40 rounded border border-zinc-300 px-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
          />
        </label>
      )}

      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
        Reason (required)
        <textarea
          name="reason"
          required
          rows={2}
          placeholder={`Why ${action}?`}
          className="rounded border border-zinc-300 px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
      </label>

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-zinc-50 hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
        >
          {pending ? "Submitting..." : `Confirm ${action}`}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() => {
            setAction(null);
            setError(null);
          }}
          className="rounded border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
