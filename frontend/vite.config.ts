import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Keep root-relative URLs by default. Set VITE_ASSET_BASE (for example,
// /portal/) only when serving the built application below a URL prefix.
const assetBase = process.env.VITE_ASSET_BASE || "/";

export default defineConfig({
  base: assetBase,
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/auth": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    exclude: ["node_modules/**", "e2e/**"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        "src/main.tsx",
        "src/test/**",
        "src/api/types.ts",
      ],
      thresholds: {
        statements: 85,
      },
    },
  },
});
