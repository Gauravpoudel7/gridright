"use client";

import { useActionState, useState } from "react";

import {
  submitPairingCodeAction,
  type MeterBindingResult,
} from "@/app/actions/meter-binding";

type BindingStatus = "unbound" | "pairing_pending" | "bound" | "binding_failed";

const inputClass =
  "h-10 flex-1 rounded border border-zinc-300 px-3 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50";

function StatusBadge({ status }: { status: BindingStatus }) {
  const map: Record<BindingStatus, string> = {
    bound: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400",
    binding_failed: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
    pairing_pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
    unbound: "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400",
  };
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${map[status]}`}>
      {status.replace("_", " ")}
    </span>
  );
}

/**
 * Meter binding via pairing code (spec §3.2). The seller enters the meter's
 * pairing code (NOT a free-text meter id); the backend exchanges it with the
 * virtual-smart-meter service. On success the binding is permanent — there is
 * no unbind/rebind path, so once `bound` the form is replaced by a read-only
 * confirmation.
 */
export function MeterBindingSection({
  initialStatus,
  initialMeterId,
}: {
  initialStatus: BindingStatus;
  initialMeterId: string | null;
}) {
  const [status, setStatus] = useState<BindingStatus>(initialStatus);
  const [meterId, setMeterId] = useState<string | null>(initialMeterId);
  const [deviceToken, setDeviceToken] = useState<string | null>(null);

  const [state, formAction, pending] = useActionState(
    async (_prev: MeterBindingResult, formData: FormData) => {
      const r = await submitPairingCodeAction(formData);
      if (r.ok && r.status) {
        setStatus(r.status as BindingStatus);
        if (r.meterId) setMeterId(r.meterId);
        if (r.deviceToken) setDeviceToken(r.deviceToken);
      }
      return r;
    },
    { ok: true } as MeterBindingResult,
  );

  return (
    <section className="mb-6 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Meter binding</h2>
        <StatusBadge status={status} />
      </div>

      {status === "bound" ? (
        <>
          <p className="text-sm text-zinc-700 dark:text-zinc-300">
            Meter <span className="font-mono text-xs">{meterId}</span> is bound to your
            account. This is permanent — a meter can only ever belong to one seller.
          </p>
          {deviceToken && (
            <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-900/20 dark:text-amber-300">
              Meter ingest token (shown once — your meter device uses it to push
              readings): <code className="font-mono break-all">{deviceToken}</code>
            </div>
          )}
        </>
      ) : (
        <>
          <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
            Enter the pairing code printed on your meter&apos;s install docs to bind it
            to your account.
          </p>
          <form action={formAction} className="flex flex-col gap-2 sm:flex-row">
            <input
              name="pairing_code"
              type="text"
              required
              placeholder="Pairing code"
              className={inputClass}
              autoComplete="off"
            />
            <button
              type="submit"
              disabled={pending}
              className="h-10 rounded bg-zinc-900 px-4 font-medium text-zinc-50 hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              {pending ? "Binding…" : "Bind meter"}
            </button>
          </form>
          {status === "binding_failed" && state.ok && state.reason && (
            <p className="mt-3 text-sm text-red-600 dark:text-red-400">
              {state.reason} You can try again with a new code.
            </p>
          )}
          {!state.ok && state.error && (
            <p className="mt-3 text-sm text-red-600 dark:text-red-400">{state.error}</p>
          )}
        </>
      )}
    </section>
  );
}
