import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],

  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },

  server: {
    host: "0.0.0.0",
    port: 3000,
    // Shopify CLI generates a new quick-tunnel subdomain on every dev run.
    // Restrict the exception to Cloudflare quick tunnels instead of allowing all hosts.
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
