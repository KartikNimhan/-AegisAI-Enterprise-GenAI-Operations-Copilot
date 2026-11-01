import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, vi } from 'vitest'

// Build-time settings must not leak into tests. Vite loads `.env.local` in every mode, including
// Vitest's `test` mode, so a developer's local sign-in settings would otherwise reach every test
// (CI never has that file: `*.local` is ignored by Git). Every reader treats an empty value as
// absent (`||` in auth/oidcConfig.ts, `if (buildTimeUrl)` in config.ts), so tests behave as in CI.
// This runs before each test file's own hooks, so a test that stubs a value on purpose still wins.
const BUILD_TIME_SETTINGS = ['VITE_OIDC_AUTHORITY', 'VITE_OIDC_CLIENT_ID', 'VITE_API_BASE_URL'] as const

beforeEach(() => {
  for (const name of BUILD_TIME_SETTINGS) vi.stubEnv(name, '')
})

afterEach(() => {
  vi.unstubAllEnvs()
})
