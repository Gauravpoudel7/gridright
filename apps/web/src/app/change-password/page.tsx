import { redirect } from "next/navigation";
import "server-only";

import { getCurrentUser } from "@/lib/supabase/get-current-user";
import { ChangePasswordForm } from "./change-password-form";

export const metadata = { title: "Change your password — GridRight" };

/** Forced password-change screen (spec §4). Reachable only by an
 *  authenticated seller; the API independently gates every OTHER seller route
 *  until must_change_password clears, so this page is the mandatory first stop
 *  after an operator-issued temporary password. */
export default async function ChangePasswordPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (user.role !== "seller") redirect("/operator/login?error=not_seller");

  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-12 dark:bg-black">
      <div className="w-full max-w-sm rounded-lg border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="mb-2 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
          Set a new password
        </h1>
        <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
          You signed in with a temporary password. Choose a new one to continue
          to your dashboard.
        </p>
        <ChangePasswordForm />
      </div>
    </div>
  );
}
