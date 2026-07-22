"use client";

import { useActionState, useEffect } from "react";
import { useRouter } from "next/navigation";

import { changePasswordAction, type ChangePasswordResult } from "@/app/actions/password";

const INITIAL: ChangePasswordResult = { ok: false };

const inputClass =
  "h-10 rounded border border-zinc-300 px-3 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50";
const labelClass =
  "flex flex-col gap-1 text-sm font-medium text-zinc-700 dark:text-zinc-300";

/** Forced password change for operator-provisioned sellers (spec §4). On
 *  success the gate clears server-side and we push to the dashboard. */
export function ChangePasswordForm() {
  const router = useRouter();
  const [state, formAction, pending] = useActionState(
    async (_prev: ChangePasswordResult, formData: FormData) =>
      changePasswordAction(formData),
    INITIAL,
  );

  useEffect(() => {
    if (state.ok) router.push("/dashboard");
  }, [state.ok, router]);

  return (
    <form action={formAction} className="flex flex-col gap-4">
      <label className={labelClass}>
        New password
        <input
          name="new_password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          className={inputClass}
        />
        <span className="text-xs font-normal text-zinc-500">At least 8 characters.</span>
      </label>
      <label className={labelClass}>
        Confirm new password
        <input
          name="confirm_password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
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
        {pending ? "Updating…" : "Set new password"}
      </button>
    </form>
  );
}
