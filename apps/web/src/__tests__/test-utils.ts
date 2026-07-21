import { RedirectError } from "./mocks/next-navigation";

export interface MockUser {
  id: string;
  email: string | null;
  role: "seller" | "operator";
}

export function mockSellerUser(): MockUser {
  return { id: "seller-1", email: "seller@test.com", role: "seller" };
}

export function mockOperatorUser(): MockUser {
  return { id: "op-1", email: "operator@grid.com", role: "operator" };
}

/** Create a mock Supabase session response */
export function mockSession(token = "mock-access-token") {
  return {
    data: { session: { access_token: token } },
    error: null,
  };
}

/** Build a Response object from JSON data */
export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Expect a RedirectError with the given URL.
 * Call inside a try/catch on `await page()` or use `expect().toThrow()`.
 */
export function expectRedirect(fn: () => unknown, url: string) {
  expect(fn).toThrow(RedirectError);
  try {
    fn();
  } catch (e: unknown) {
    if (e instanceof RedirectError) {
      expect(e.url).toBe(url);
    }
  }
}

export { RedirectError };
