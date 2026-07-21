import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "next/navigation": path.resolve(__dirname, "./src/__tests__/mocks/next-navigation.ts"),
      "next/cache": path.resolve(__dirname, "./src/__tests__/mocks/next-cache.ts"),
      "next/headers": path.resolve(__dirname, "./src/__tests__/mocks/next-headers.ts"),
      "server-only": path.resolve(__dirname, "./src/__tests__/mocks/server-only.ts"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
