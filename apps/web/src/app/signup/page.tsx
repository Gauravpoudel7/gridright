import Link from "next/link";

import { SignupForm } from "./signup-form";

export const metadata = {
  title: "Seller sign up — GridRight",
};

export default function SellerSignupPage() {
  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-12 dark:bg-black">
      <div className="w-full max-w-sm rounded-lg border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="mb-2 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
          Create a seller account
        </h1>
        <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
          Contribute your solar surplus to the community pool and track your
          payouts.
        </p>
        <SignupForm />
        <p className="mt-6 text-sm text-zinc-600 dark:text-zinc-400">
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-medium text-zinc-900 underline dark:text-zinc-50"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
