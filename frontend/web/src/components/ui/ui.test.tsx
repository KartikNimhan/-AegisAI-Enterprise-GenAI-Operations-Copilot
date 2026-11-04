/**
 * M10.1 design-system primitives and theme switching: behaviour and accessibility (axe).
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { expectAxe } from '../../test/axe'
import { ThemeSwitch } from '../../theme/ThemeSwitch'
import {
  THEME_STORAGE_KEY,
  applyThemePreference,
  readThemePreference,
  saveThemePreference,
} from '../../theme/theme'
import { Badge } from './Badge'
import { Button } from './Button'
import { SidePanel } from './SidePanel'
import { ErrorState, LoadingState } from './States'

describe('theme preference', () => {
  beforeEach(() => {
    window.localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('defaults to the system theme and sets no data-theme', () => {
    expect(readThemePreference()).toBe('system')
    applyThemePreference('system')
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })

  it('persists an explicit choice and applies it', () => {
    saveThemePreference('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(readThemePreference()).toBe('dark')
    applyThemePreference('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('choosing System forgets the saved choice', () => {
    saveThemePreference('light')
    saveThemePreference('system')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
  })

  it('ignores a corrupted saved value', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'neon')
    expect(readThemePreference()).toBe('system')
  })

  it('still works when storage is unavailable', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readThemePreference()).toBe('system')
    expect(() => saveThemePreference('dark')).not.toThrow()
    getItem.mockRestore()
    setItem.mockRestore()
  })
})

describe('ThemeSwitch', () => {
  beforeEach(() => {
    window.localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('is a labelled radio group that applies and saves the choice', async () => {
    const user = userEvent.setup()
    const { container } = render(<ThemeSwitch />)

    expect(screen.getByRole('group', { name: 'Theme' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'System' })).toBeChecked()

    await user.click(screen.getByRole('radio', { name: 'Dark' }))

    expect(screen.getByRole('radio', { name: 'Dark' })).toBeChecked()
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    await expectAxe(container)
  })

  it('can be operated with the arrow keys', async () => {
    const user = userEvent.setup()
    render(<ThemeSwitch />)

    screen.getByRole('radio', { name: 'System' }).focus()
    await user.keyboard('{ArrowRight}')

    expect(screen.getByRole('radio', { name: 'Light' })).toBeChecked()
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})

describe('Button', () => {
  it('never submits a form by default and announces when busy', async () => {
    const onSubmit = vi.fn((event: Event) => event.preventDefault())
    const user = userEvent.setup()
    const { container } = render(
      <form onSubmit={(e) => onSubmit(e.nativeEvent)}>
        <Button>Plain</Button>
        <Button busy variant="primary">
          Saving
        </Button>
      </form>,
    )

    await user.click(screen.getByRole('button', { name: 'Plain' }))

    expect(onSubmit).not.toHaveBeenCalled()
    const busy = screen.getByRole('button', { name: 'Saving' })
    expect(busy).toBeDisabled()
    expect(busy).toHaveAttribute('aria-busy', 'true')
    await expectAxe(container)
  })
})

describe('states and badges', () => {
  it('loading is a status, errors are alerts with a retry', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    const { container } = render(
      <div>
        <LoadingState label="Loading sources…" />
        <ErrorState title="Could not load" description="Try again later." onRetry={onRetry} />
        <Badge tone="citation">S1</Badge>
      </div>,
    )

    expect(screen.getByRole('status')).toHaveTextContent('Loading sources…')
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
    await expectAxe(container)
  })
})

function PanelHarness() {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Open source
      </button>
      <SidePanel open={open} title="Source S1" onClose={() => setOpen(false)}>
        <p>Passage</p>
        <a href="#x">Inside link</a>
      </SidePanel>
    </div>
  )
}

describe('SidePanel', () => {
  it('is a labelled modal dialog that takes focus and returns it on Escape', async () => {
    const user = userEvent.setup()
    render(<PanelHarness />)
    const opener = screen.getByRole('button', { name: 'Open source' })

    await user.click(opener)

    const dialog = screen.getByRole('dialog', { name: 'Source S1' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    await expectAxe(document.body)

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('keeps Tab inside the panel', async () => {
    const user = userEvent.setup()
    render(<PanelHarness />)
    await user.click(screen.getByRole('button', { name: 'Open source' }))

    await user.tab() // Close -> link
    expect(screen.getByRole('link', { name: 'Inside link' })).toHaveFocus()
    await user.tab() // link -> wraps to Close
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    await user.tab({ shift: true }) // Close -> wraps to link
    expect(screen.getByRole('link', { name: 'Inside link' })).toHaveFocus()
  })

  it('closes from the close button and returns focus', async () => {
    const user = userEvent.setup()
    render(<PanelHarness />)
    const opener = screen.getByRole('button', { name: 'Open source' })
    await user.click(opener)

    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Close' }))
    })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })
})
