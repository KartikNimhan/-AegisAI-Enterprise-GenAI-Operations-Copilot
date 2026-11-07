/**
 * Theme preference (M10 decision 4): follow the operating system by default, or let the user pick
 * Light or Dark; the choice is kept across sessions in this browser.
 *
 * "system" removes `data-theme` so tokens.css follows `prefers-color-scheme`; "light" and "dark" set
 * it explicitly. Storage can be unavailable (private windows, blocked site data), so every access is
 * guarded and the page still renders with the system theme.
 */
import { useCallback, useEffect, useState } from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'

export const THEME_STORAGE_KEY = 'aegisai.theme'
const PREFERENCES: readonly ThemePreference[] = ['system', 'light', 'dark']

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === 'string' && (PREFERENCES as readonly string[]).includes(value)
}

export function readThemePreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isThemePreference(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

export function applyThemePreference(preference: ThemePreference, root: HTMLElement = document.documentElement) {
  if (preference === 'system') delete root.dataset.theme
  else root.dataset.theme = preference
}

export function saveThemePreference(preference: ThemePreference) {
  try {
    if (preference === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY)
    else window.localStorage.setItem(THEME_STORAGE_KEY, preference)
  } catch {
    // Not persisted; the choice still applies for this page.
  }
}

/** Applied once at start-up, before the first render, so the page never flashes the wrong theme. */
export function applyStoredThemePreference() {
  applyThemePreference(readThemePreference())
}

export function useThemePreference(): [ThemePreference, (preference: ThemePreference) => void] {
  const [preference, setPreference] = useState<ThemePreference>(readThemePreference)

  useEffect(() => {
    applyThemePreference(preference)
  }, [preference])

  const choose = useCallback((next: ThemePreference) => {
    saveThemePreference(next)
    setPreference(next)
  }, [])

  return [preference, choose]
}
