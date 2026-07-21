export class RedirectError extends Error {
  url: string;
  constructor(url: string) {
    super("NEXT_REDIRECT");
    this.url = url;
    this.name = "RedirectError";
  }
}

export function redirect(url: string): never {
  throw new RedirectError(url);
}
