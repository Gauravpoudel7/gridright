import { permanentRedirect } from "next/navigation";

/**
 * Direct self-serve signup is gone — seller accounts are only created by an
 * operator approving an application (spec §3.1). Old bookmarks and links land
 * on the application form instead.
 */
export default function SellerSignupPage() {
  permanentRedirect("/apply");
}
