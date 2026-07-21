import { describe, it, expect, vi } from "vitest";

// The proxy module imports @supabase/ssr at top level; stub it so we can
// import the matcher config without a Supabase environment.
vi.mock("@supabase/ssr", () => ({ createServerClient: vi.fn() }));

import { config } from "@/proxy";

/**
 * /demo must stay out of the proxy's role-gating (DEMO-ONLY requirement:
 * the demo works fully signed-out). This test fails if a future matcher
 * edit pulls /demo (or everything, e.g. "/:path*") into the proxy.
 */
describe("proxy matcher — /demo exclusion", () => {
  // Minimal Next.js-style matcher check: ":path*" segments match any suffix.
  function matcherCovers(pattern: string, path: string): boolean {
    const regex = new RegExp(
      "^" +
        pattern
          .replace(/:[A-Za-z0-9_]+\*/g, ".*")
          .replace(/:[A-Za-z0-9_]+/g, "[^/]+") +
        "$",
    );
    return regex.test(path) || regex.test(path + "/");
  }

  it("no matcher pattern covers /demo", () => {
    for (const pattern of config.matcher) {
      expect(
        matcherCovers(pattern, "/demo"),
        `matcher pattern "${pattern}" must not cover /demo`,
      ).toBe(false);
      expect(
        matcherCovers(pattern, "/demo/anything"),
        `matcher pattern "${pattern}" must not cover /demo subpaths`,
      ).toBe(false);
    }
  });

  it("matcher still covers the dashboards (sanity check)", () => {
    const covers = (path: string) =>
      config.matcher.some((p: string) => matcherCovers(p, path));
    expect(covers("/dashboard")).toBe(true);
    expect(covers("/operator/dashboard")).toBe(true);
  });
});
