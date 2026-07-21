"use client";

import { useActionState } from "react";
import { useSearchParams } from "next/navigation";

import { loginAction, type LoginResult } from "@/app/actions/auth";

const INITIAL: LoginResult = { ok: true };

export function LoginForm({ next }: { next: string }) {
  const [state, formAction, pending] = useActionState(
    async (_prev: LoginResult, formData: FormData) =>
      loginAction(formData),
    INITIAL,
  );
  const searchParams = useSearchParams();
  const errorFromQuery = searchParams.get("error");

  return (
    <form action={formAction} className="flex flex-col gap-4">
      <input type="hidden" name="next" value={next} />
      <label className="flex flex-col gap-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Email
        <input
          name="email"
          type="email"
          required
          autoComplete="email"
          className="h-10 rounded border border-zinc-300 px-3 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Password
        <input
          name="password"
          type="password"
          required
          autoComplete="current-password"
          className="h-10 rounded border border-zinc-300 px-3 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        />
      </label>
      {errorFromQuery === "not_operator" && (
        <p className="text-sm text-red-600 dark:text-red-400">
          This account is not an operator. Sign in via the seller login.
        </p>
      )}
      {errorFromQuery === "not_seller" && (
        <p className="text-sm text-red-600 dark:text-red-400">
          This account is an operator. Sign in via the operator login.
        </p>
      )}
      {!state.ok && state.error && (
        <p className="text-sm text-red-600 dark:text-red-400">{state.error}</p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="h-10 rounded bg-zinc-900 font-medium text-zinc-50 transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
      >
        {pending ? "Signing in..." : "Sign in"}
      </button>
    </form>
  );
}
