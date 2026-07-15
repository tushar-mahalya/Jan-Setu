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
});
