import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

/**
 * The build lands in `dist/`, which FastAPI serves as it is; in development
 * the API calls are proxied so the app can keep using relative URLs in both
 * situations and never needs to know where the backend lives.
 */
const BACKEND = process.env.SENTRY_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/folders": { target: BACKEND, changeOrigin: true },
      "/recordings": { target: BACKEND, changeOrigin: true },
      "/prompts": { target: BACKEND, changeOrigin: true },
    },
  },
});
