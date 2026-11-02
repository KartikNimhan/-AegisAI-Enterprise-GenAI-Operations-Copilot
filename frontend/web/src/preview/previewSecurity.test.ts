/**
 * The preview must stay out of the real application. These tests read the source files, so a
 * future import of preview code into the real app's graph fails here.
 */

import { describe, expect, it } from 'vitest'
import indexHtml from '../../index.html?raw'

const sources = import.meta.glob('/src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const isPreviewFile = (path: string) =>
  path.startsWith('/src/preview/') || path === '/src/dev-preview.tsx'
const isTest = (path: string) => /\.test\.tsx?$/.test(path)

describe('production isolation', () => {
  it('finds the source files it is meant to check', () => {
    expect(Object.keys(sources)).toContain('/src/main.tsx')
    expect(Object.keys(sources)).toContain('/src/dev-preview.tsx')
  })

  it('no application file imports preview code', () => {
    const offenders = Object.entries(sources)
      .filter(([path]) => !isPreviewFile(path) && !isTest(path))
      .filter(([, text]) => /preview\/|dev-preview|PreviewApp|mockApi|mockData/.test(text))
      .map(([path]) => path)

    expect(offenders).toEqual([])
  })

  it('the real entry point still wraps the app in OIDC sign-in and the auth gate', () => {
    const main = sources['/src/main.tsx']
    expect(main).toContain('<OidcAuthProvider>')
    expect(main).toContain('<AuthGate>')
    expect(main).not.toMatch(/preview/i)
  })

  it('index.html (the only page the production build bundles) does not reference the preview', () => {
    expect(indexHtml).toContain('/src/main.tsx')
    expect(indexHtml).not.toMatch(/preview.html|dev-preview|PreviewApp/i)
  })

  it('the preview entry refuses to run outside development on a local host', () => {
    const entry = sources['/src/dev-preview.tsx']
    expect(entry).toContain('previewAllowed(import.meta.env.DEV')
    expect(entry).toContain('The UI preview is only available in local development.')
  })

  it('the auth gate and sign-in provider know nothing about the preview', () => {
    for (const path of ['/src/auth/AuthGate.tsx', '/src/auth/OidcAuthProvider.tsx']) {
      expect(sources[path]).not.toMatch(/preview/i)
    }
  })
})
