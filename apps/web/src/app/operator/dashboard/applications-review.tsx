"use client";

import { useActionState, useState } from "react";

import {
  approveApplicationAction,
  rejectApplicationAction,
  type OperatorReviewResult,
} from "@/app/actions/onboarding";

type Application = {
  id: string;
  full_name: string;
  gmail: string;
  location_text: string;
  application_status: string;
  created_at: string;
};

type Pool = { id: string; name?: string };

const INITIAL: OperatorReviewResult = { ok: true };

function ApproveForm({
  applicationId,
  pools,
  onDone,
}: {
  applicationId: string;
  pools: Pool[];
  onDone: () => void;
}) {
  const [state, formAction, pending] = useActionState(
    async (_prev: OperatorReviewResult, formData: FormData) => {
      const r = await approveApplicationAction(formData);
      if (r.ok) onDone();
      return r;
    },
    INITIAL,
  );
  return (
    <form action={formAction} className="mt-3 flex flex-col gap-2">
      <input type="hidden" name="application_id" value={applicationId} />
      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
        Assign community pool
        <select
          name="community_pool_id"
          required
          className="h-9 rounded border border-zinc-300 px-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        >
          <option value="">— select pool —</option>
          {pools.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name ?? p.id}
            </option>
          ))}
        </select>
      </label>
      {!state.ok && state.error && (
        <p className="text-xs text-red-600 dark:text-red-400">{state.error}</p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="h-8 rounded bg-emerald-700 px-3 text-xs font-medium text-white hover:bg-emerald-800 disabled:opacity-50"
      >
        {pending ? "Approving…" : "Approve & send credentials"}
      </button>
    </form>
  );
}

function RejectForm({
  applicationId,
  onDone,
}: {
  applicationId: string;
  onDone: () => void;
}) {
  const [state, formAction, pending] = useActionState(
    async (_prev: OperatorReviewResult, formData: FormData) => {
      const r = await rejectApplicationAction(formData);
      if (r.ok) onDone();
      return r;
    },
    INITIAL,
  );
  return (
    <form action={formAction} className="mt-3 flex flex-col gap-2">
      <input type="hidden" name="application_id" value={applicationId} />
      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
        Rejection reason
        <input
          name="reason"
          type="text"
          required
          placeholder="e.g. Ownership document unreadable"
          className="h-9 rounded border border-zinc-300 px-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
      </label>
      {!state.ok && state.error && (
        <p className="text-xs text-red-600 dark:text-red-400">{state.error}</p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="h-8 rounded bg-red-700 px-3 text-xs font-medium text-white hover:bg-red-800 disabled:opacity-50"
      >
        {pending ? "Rejecting…" : "Reject"}
      </button>
    </form>
  );
}

/**
 * Operator identity-review panel (spec §3.1). Shows pending applications and
 * lets the operator approve (assigning a community pool) or reject (with a
 * reason). On approve the backend creates the auth user, generates a temp
 * password, and emails it — the operator never sees the password.
 */
export function ApplicationsReview({
  initialApplications,
  pools,
}: {
  initialApplications: Application[];
  pools: Pool[];
}) {
  const [apps, setApps] = useState(initialApplications);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [action, setAction] = useState<"approve" | "reject" | null>(null);

  function dismiss(id: string) {
    setApps((prev) => prev.filter((a) => a.id !== id));
    setExpanded(null);
    setAction(null);
  }

  if (apps.length === 0) {
    return <p className="text-sm text-zinc-500">No pending applications.</p>;
  }

  return (
    <ul className="flex max-h-[32rem] flex-col gap-4 overflow-y-auto">
      {apps.map((app) => (
        <li
          key={app.id}
          className="rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-medium text-zinc-900 dark:text-zinc-50">
                {app.full_name}
              </p>
              <p className="text-xs text-zinc-500">{app.gmail}</p>
              <p className="text-xs text-zinc-500">{app.location_text}</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setExpanded(app.id);
                  setAction("approve");
                }}
                className="h-7 rounded bg-emerald-100 px-2 text-xs font-medium text-emerald-800 hover:bg-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400"
              >
                Approve
              </button>
              <button
                type="button"
                onClick={() => {
                  setExpanded(app.id);
                  setAction("reject");
                }}
                className="h-7 rounded bg-red-100 px-2 text-xs font-medium text-red-800 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400"
              >
                Reject
              </button>
            </div>
          </div>

          {expanded === app.id && action === "approve" && (
            <ApproveForm
              applicationId={app.id}
              pools={pools}
              onDone={() => dismiss(app.id)}
            />
          )}
          {expanded === app.id && action === "reject" && (
            <RejectForm
              applicationId={app.id}
              onDone={() => dismiss(app.id)}
            />
          )}
        </li>
      ))}
    </ul>
  );
}
