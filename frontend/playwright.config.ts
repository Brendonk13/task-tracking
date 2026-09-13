import path from "node:path"
import { defineConfig, devices } from "@playwright/test"

/**
 * Playwright smoke test against a REAL backend (PLAN.md task 8.1).
 *
 * Two servers are started for the run:
 *  - Django on :8000 with a throwaway SQLite database (frontend/e2e/e2e_settings.py).
 *    The port is fixed because vite.config.ts proxies /api to http://localhost:8000.
 *  - Vite on :5180 (not the default 5173; 5173-5175 are often taken by other dev servers
 *    on this machine). The port is passed on the command line so vite.config.ts stays
 *    untouched; the /api proxy still points at :8000.
 *
 * reuseExistingServer is false for both so the test never runs against someone's
 * real dev backend and its real database.
 */

const FRONTEND_PORT = 5180
const BACKEND_PORT = 8000

const frontendDir = import.meta.dirname
const e2eDir = path.join(frontendDir, "e2e")
const backendDir = path.resolve(frontendDir, "..", "backend")
const e2eDbPath = path.join(e2eDir, ".tmp", "e2e.sqlite3")

const backendEnv = {
  ...process.env,
  DJANGO_SETTINGS_MODULE: "e2e_settings",
  PYTHONPATH: e2eDir,
}

export default defineConfig({
  testDir: "./e2e",
  // *.e2e.ts, not *.spec.ts: vitest's default glob would otherwise pick these up.
  testMatch: /.*\.e2e\.ts$/,
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [["list"]],
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Fresh database every run: drop the previous e2e DB, migrate (seeds the ten
      // built-in statuses), then serve. --noreload keeps it a single process so
      // Playwright can shut it down cleanly.
      command: [
        `rm -f "${e2eDbPath}"`,
        "uv run python manage.py migrate --no-input",
        `uv run python manage.py runserver 127.0.0.1:${BACKEND_PORT} --noreload`,
      ].join(" && "),
      cwd: backendDir,
      env: backendEnv,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/openapi.json`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `pnpm exec vite --port ${FRONTEND_PORT} --strictPort`,
      cwd: frontendDir,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
})
