import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex max-w-2xl flex-col items-center gap-8 px-8 py-24">
        <h1 className="text-center text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          GridRight
        </h1>
        <p className="text-center text-lg leading-7 text-zinc-600 dark:text-zinc-400">
          AI-assisted, utility-moderated settlement for distributed solar energy.
          Sign in to access your dashboard.
        </p>
        <div className="flex flex-col gap-4 sm:flex-row">
          <Link
            href="/login"
            className="flex h-12 items-center justify-center rounded-full bg-zinc-900 px-6 text-base font-medium text-zinc-50 transition-colors hover:bg-zinc-700 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            Seller sign in
          </Link>
          <Link
            href="/operator/login"
            className="flex h-12 items-center justify-center rounded-full border border-zinc-300 px-6 text-base font-medium text-zinc-900 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
          >
            Operator sign in
          </Link>
          <Link
            href="/demo/live"
            className="flex h-12 items-center justify-center rounded-full border border-emerald-400 bg-emerald-50 px-6 text-base font-medium text-emerald-900 transition-colors hover:bg-emerald-100 dark:border-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-300"
          >
            Live Demo
          </Link>
        </div>
      </main>
    </div>
  );
}
