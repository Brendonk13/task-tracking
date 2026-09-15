/// <reference types="vitest/config" />
import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { configDefaults } from "vitest/config"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // Loopback only: this app is single-user and must not be reachable from the
    // network, so never pass --host / set this to 0.0.0.0.
    host: "127.0.0.1",
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  preview: {
    host: "127.0.0.1",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: [...configDefaults.exclude, "e2e/**"],
    css: false,
  },
})
