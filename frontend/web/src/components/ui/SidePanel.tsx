import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '../Icon'
import styles from './SidePanel.module.css'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * A modal side panel (M10.1; used by the citation source panel, M10.5).
 *
 * Accessibility: a <dialog> with `aria-modal` and a labelled title; focus moves into the panel
 * when it opens, Tab and Shift+Tab stay inside it, Escape or the backdrop closes it, and focus
 * returns to the element that opened it (WCAG 2.4.3, 2.1.2).
 */
export function SidePanel({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}) {
  const titleId = useId()
  const panelRef = useRef<HTMLDialogElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const openerRef = useRef<Element | null>(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    openerRef.current = document.activeElement
    closeRef.current?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !panelRef.current) return
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      const opener = openerRef.current
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div className={styles.layer}>
      <div className={styles.backdrop} onClick={onClose} aria-hidden="true" />
      {/* A native <dialog> rendered open: its role is implicit. It is not opened with
          showModal() (focus handling is done here, identically in browsers and jsdom). */}
      <dialog ref={panelRef} open className={styles.panel} aria-modal="true" aria-labelledby={titleId}>
        {/* Plain divs, not <header>/<footer>: portalled into <body> they would become extra
            page-level banner and contentinfo landmarks. */}
        <div className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
          <button
            ref={closeRef}
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close"
          >
            <Icon name="close" size={18} />
          </button>
        </div>
        <div className={styles.body}>{children}</div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </dialog>
    </div>,
    document.body,
  )
}
