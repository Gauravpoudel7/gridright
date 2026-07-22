import Link from "next/link";

import { ApplyForm, StatusChecker } from "./apply-form";

export const metadata = {
  title: "Become a seller — GridRight",
};

/** Public seller application page (spec §3.1). No account needed — an
 *  operator reviews the application and emails credentials on approval. */
export default function ApplyPage() {
  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-12 dark:bg-black">
      <div className="w-full max-w-md">
        <div className="rounded-lg border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
          <h1 className="mb-2 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            Apply to become a seller
          </h1>
          <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
            Tell us who you are and where your panels live. An operator reviews
            every application; once approved you&apos;ll receive login
            credentials by email.
          </p>
          <ApplyForm />
          <p className="mt-6 text-sm text-zinc-600 dark:text-zinc-400">
            Already approved?{" "}
            <Link href="/login" className="font-medium text-zinc-900 underline dark:text-zinc-50">
              Sign in
            </Link>
          </p>
        </div>
        <div className="mt-4">
          <StatusChecker />
        </div>
      </div>
    </div>
  );
}
