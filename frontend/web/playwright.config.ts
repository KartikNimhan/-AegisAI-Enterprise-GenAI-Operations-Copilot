/**
 * Browser tests (M10.0). Two projects, two servers:
 *
 * - `preview`: the development-only UI preview (`preview.html`) on the Vite dev server, which
 *   renders the real app against mock data with no sign-in and no network (src/preview/*). Used
 *   for accessibility, responsive, keyboard, focus and reduced-motion checks in both themes.
 * - `production-csp`: the PRODUCTION build (`dist/`, run `npm run build` first) served by
 *   `vite preview`, with every response given the same Content-Security-Policy that
 *   docker-entrypoint.sh produces in the container (see e2e/support/policy.ts). The backend and
 *   the identity provider are mocked inside the browser; nothing leaves the machine.
 *
 * No test calls a real backend, identity provider or language model.
 * Retries are off on purpose: a flaky test must be visible, not retried until it passes.
 */
import { defineConfig, devices } from '@playwright/test'

const DEV_PORT = 5173
const PREVIEW_PORT = 4173
const CI = Boolean(process.env.CI)

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: CI,
  retries: 0,
  workers: CI ? 2 : undefined,
  reporter: CI ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]] : 'list',
  use: {
    ...devices['Desktop Chrome'],
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'preview',
      testMatch: /preview\..+\.spec\.ts$/,
      use: { baseURL: `http://127.0.0.1:${DEV_PORT}` },
    },
    {
      name: 'production-csp',
      testMatch: /production-csp\.spec\.ts$/,
      use: { baseURL: `http://127.0.0.1:${PREVIEW_PORT}` },
    },
  ],
  webServer: [
    {
      command: `npx vite --host 127.0.0.1 --port ${DEV_PORT} --strictPort`,
      url: `http://127.0.0.1:${DEV_PORT}/preview.html`,
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
    {
      command: `npx vite preview --host 127.0.0.1 --port ${PREVIEW_PORT} --strictPort`,
      url: `http://127.0.0.1:${PREVIEW_PORT}/`,
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
  ],
})
