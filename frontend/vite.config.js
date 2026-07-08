import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the FastAPI backend so we can use same-origin paths.
// PREVIEW TOGGLE: DEV_API_TARGET defaults to the local backend; set it to the live API
// (e.g. https://d2qy3qqpz2ebmu.cloudfront.net) to preview against real data without a
// local backend. Revert to localhost for normal dev.
const DEV_API_TARGET = process.env.DEV_API_TARGET || "http://localhost:8000";
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: DEV_API_TARGET, changeOrigin: true, secure: true },
      "/health": { target: DEV_API_TARGET, changeOrigin: true, secure: true },
    },
  },
});
