import { Suspense } from "react";
import Link from "next/link";

import { LoginForm } from "../../login/login-form";

export const metadata = {
  title: "Operator sign in — GridRight",
};

export default function OperatorLoginPage() {
  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-12 dark:bg-black">
      <div className="w-full max-w-sm rounded-lg border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="mb-2 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
          Operator sign in
        </h1>
        <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
          Sign in to manage the community pool and review AI recommendations.
        </p>
        <Suspense fallback={null}>
          <LoginForm next="/operator/dashboard" />
        </Suspense>
        <p className="mt-6 text-sm text-zinc-600 dark:text-zinc-400">
          A seller?{" "}
          <Link
            href="/login"
            className="font-medium text-zinc-900 underline dark:text-zinc-50"
          >
            Sign in here
          </Link>
        </p>
      </div>
    </div>
  );
}
