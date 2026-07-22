"use client";

import { useActionState, useState } from "react";

import {
  submitApplicationAction,
  checkApplicationStatusAction,
  resubmitApplicationAction,
  type SubmitApplicationResult,
  type ApplicationStatusResult,
} from "@/app/actions/onboarding";

const INITIAL: SubmitApplicationResult = { ok: true };

const inputClass =
  "h-10 rounded border border-zinc-300 px-3 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50";
const labelClass =
  "flex flex-col gap-1 text-sm font-medium text-zinc-700 dark:text-zinc-300";

/** The public seller application: identity + house-ownership details. On
 *  success it shows the one-time edit token the applicant needs to check
 *  status / resubmit — there is no login yet (spec §3.1). */
export function ApplyForm() {
  const [state, formAction, pending] = useActionState(
    async (_prev: SubmitApplicationResult, formData: FormData) =>
      submitApplicationAction(formData),
    INITIAL,
  );

  if (state.ok && state.applicationId && state.editToken) {
    return <SubmittedNotice applicationId={state.applicationId} editToken={state.editToken} />;
  }

  return (
    <form action={formAction} className="flex flex-col gap-4">
      <label className={labelClass}>
        Full name
        <input name="full_name" type="text" required autoComplete="name" className={inputClass} />
      </label>
      <label className={labelClass}>
        Date of birth
        <input name="dob" type="date" required className={inputClass} />
      </label>
      <label className={labelClass}>
        House-ownership document (URL)
        <input
          name="ownership_doc_url"
          type="url"
          required
          placeholder="https://…"
          className={inputClass}
        />
        <span className="text-xs font-normal text-zinc-500">
          A link to your deed / ownership proof. Upload to any file host and paste the link.
        </span>
      </label>
      <label className={labelClass}>
        Gmail address
        <input name="gmail" type="email" required autoComplete="email" className={inputClass} />
        <span className="text-xs font-normal text-zinc-500">
          Your login credentials will be emailed here once approved.
        </span>
      </label>
      <label className={labelClass}>
        Location
        <input
          name="location_text"
          type="text"
          required
          placeholder="Address or area"
          className={inputClass}
        />
      </label>
      {!state.ok && state.error && (
        <p className="text-sm text-red-600 dark:text-red-400">{state.error}</p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="h-10 rounded bg-zinc-900 font-medium text-zinc-50 transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
      >
        {pending ? "Submitting…" : "Submit application"}
      </button>
    </form>
  );
}

function SubmittedNotice({
  applicationId,
  editToken,
}: {
  applicationId: string;
  editToken: string;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm dark:border-emerald-900/50 dark:bg-emerald-900/10">
        <p className="font-medium text-emerald-800 dark:text-emerald-400">
          Application submitted — pending operator review.
        </p>
        <p className="mt-2 text-zinc-700 dark:text-zinc-300">
          Save these to check your status or update a rejected application. They
          are shown only once.
        </p>
        <dl className="mt-3 space-y-1 font-mono text-xs text-zinc-800 dark:text-zinc-200">
          <div>
            <dt className="inline text-zinc-500">Application ID: </dt>
            <dd className="inline break-all">{applicationId}</dd>
          </div>
          <div>
            <dt className="inline text-zinc-500">Edit token: </dt>
            <dd className="inline break-all">{editToken}</dd>
          </div>
        </dl>
      </div>
      <StatusChecker
        defaultApplicationId={applicationId}
        defaultEditToken={editToken}
      />
    </div>
  );
}

/** Look up an application's status and, if rejected, resubmit corrected
 *  details (back to `submitted`). Token-gated — no session needed. */
export function StatusChecker({
  defaultApplicationId = "",
  defaultEditToken = "",
}: {
  defaultApplicationId?: string;
  defaultEditToken?: string;
}) {
  const [applicationId, setApplicationId] = useState(defaultApplicationId);
  const [editToken, setEditToken] = useState(defaultEditToken);
  const [result, setResult] = useState<ApplicationStatusResult | null>(null);
  const [checking, setChecking] = useState(false);

  async function check() {
    setChecking(true);
    setResult(await checkApplicationStatusAction(applicationId, editToken));
    setChecking(false);
  }

  const [resubState, resubAction, resubPending] = useActionState(
    async (_prev: SubmitApplicationResult, formData: FormData) => {
      const r = await resubmitApplicationAction(formData);
      if (r.ok) await check();
      return r;
    },
    { ok: true } as SubmitApplicationResult,
  );

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
      <h2 className="mb-3 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        Check application status
      </h2>
      <div className="flex flex-col gap-2">
        <input
          value={applicationId}
          onChange={(e) => setApplicationId(e.target.value)}
          placeholder="Application ID"
          className={inputClass}
        />
        <input
          value={editToken}
          onChange={(e) => setEditToken(e.target.value)}
          placeholder="Edit token"
          className={inputClass}
        />
        <button
          type="button"
          onClick={check}
          disabled={checking || !applicationId || !editToken}
          className="h-9 rounded border border-zinc-300 text-sm font-medium text-zinc-900 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
        >
          {checking ? "Checking…" : "Check status"}
        </button>
      </div>

      {result && !result.ok && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{result.error}</p>
      )}
      {result && result.ok && (
        <div className="mt-3 text-sm">
          <p className="text-zinc-900 dark:text-zinc-50">
            Status: <span className="font-medium">{result.status}</span>
          </p>
          {result.status === "identity_approved" && (
            <p className="mt-1 text-emerald-700 dark:text-emerald-400">
              Approved — check your email for login credentials.
            </p>
          )}
          {result.status === "identity_rejected" && (
            <div className="mt-2">
              <p className="text-red-600 dark:text-red-400">
                Rejected: {result.rejectionReason}
              </p>
              <form action={resubAction} className="mt-3 flex flex-col gap-2">
                <input type="hidden" name="application_id" value={applicationId} />
                <input type="hidden" name="edit_token" value={editToken} />
                <p className="text-xs text-zinc-500">
                  Update any fields that need correcting, then resubmit.
                </p>
                <input name="full_name" placeholder="Full name (optional)" className={inputClass} />
                <input name="ownership_doc_url" type="url" placeholder="New document URL (optional)" className={inputClass} />
                <input name="location_text" placeholder="Location (optional)" className={inputClass} />
                {!resubState.ok && resubState.error && (
                  <p className="text-sm text-red-600 dark:text-red-400">{resubState.error}</p>
                )}
                <button
                  type="submit"
                  disabled={resubPending}
                  className="h-9 rounded bg-zinc-900 text-sm font-medium text-zinc-50 hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
                >
                  {resubPending ? "Resubmitting…" : "Resubmit application"}
                </button>
              </form>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
