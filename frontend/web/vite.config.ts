import react from '@vitejs/plugin-react'
/// <reference types="vitest/config" />
import { configDefaults, defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    // Playwright's browser tests (e2e/) run with `npm run test:e2e`, not with Vitest.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
