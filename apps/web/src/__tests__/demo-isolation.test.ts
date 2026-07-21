// Guards Phase-1 isolation: demo meter code must never leak outside the demo.
// (Complements proxy-demo-exclusion.test.ts, which guards the route matcher.)
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "..");

// Files allowed to import from features/demo: the demo feature itself, the
// /demo route, and demo-tagged tests (any src/__tests__/demo-*.test.*).
const ALLOWED = [
  path.join("features", "demo"),
  path.join("app", "demo"),
];
const ALLOWED_TEST = /(^|[\\/])__tests__[\\/]demo-[\w-]+\.test\.[jt]sx?$/;

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "node_modules" ? [] : walk(full);
    return /\.(ts|tsx)$/.test(e.name) ? [full] : [];
  });
}

describe("demo isolation", () => {
  it("no file outside the demo imports from features/demo", () => {
    const offenders = walk(SRC).filter((file) => {
      const rel = path.relative(SRC, file);
      if (ALLOWED.some((a) => rel.startsWith(a) || rel.includes(a))) return false;
      if (ALLOWED_TEST.test(rel)) return false;
      const source = fs.readFileSync(file, "utf8");
      return /from\s+["'][^"']*features\/demo/.test(source);
    });
    expect(offenders.map((f) => path.relative(SRC, f))).toEqual([]);
  });
});
