import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Trace output files from the monorepo root so dependencies hoisted to the
  // root node_modules by npm workspaces are included in serverless bundles
  // (see next docs: config/next-config-js/output.md, monorepo section).
  outputFileTracingRoot: path.join(__dirname, "../../"),
};

export default nextConfig;
