import { afterEach, describe, expect, it } from 'vitest'
import { getApiBaseUrl } from './config'

afterEach(() => {
  delete window.__AEGIS_CONFIG__
})

describe('getApiBaseUrl', () => {
  it('uses the runtime URL when one is configured', () => {
    window.__AEGIS_CONFIG__ = { apiBaseUrl: 'https://api.example.test' }
    expect(getApiBaseUrl()).toBe('https://api.example.test')
  })

  it('treats an empty runtime URL as same-origin', () => {
    window.__AEGIS_CONFIG__ = { apiBaseUrl: '' }
    expect(getApiBaseUrl()).toBe(window.location.origin)
    expect(new URL('/api/v1/documents', getApiBaseUrl()).origin).toBe(window.location.origin)
  })

  it('falls back to the local default when nothing is configured', () => {
    expect(getApiBaseUrl()).toBe('http://localhost:8000')
  })
})
