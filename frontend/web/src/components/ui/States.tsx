import type { ReactNode } from 'react'
import { Icon } from '../Icon'
import { Button } from './Button'
import styles from './States.module.css'

/** A decorative spinner; the surrounding text says what is loading. */
export function Spinner({ size = 16 }: { size?: number }) {
  return <span className={styles.spinner} style={{ width: size, height: size }} aria-hidden="true" />
}

/** A polite live region (`<output>` has the implicit `status` role), so screen readers hear that
 * something is loading. */
export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <output className={styles.loading}>
      <Spinner />
      <span>{label}</span>
    </output>
  )
}

/** An error with an optional retry. `role="alert"` announces it once when it appears. */
export function ErrorState({
  title,
  description,
  onRetry,
  children,
}: {
  title: string
  description?: string
  onRetry?: () => void
  children?: ReactNode
}) {
  return (
    <div className={styles.error} role="alert">
      <span className={styles.errorIcon}>
        <Icon name="alert" size={18} />
      </span>
      <div className={styles.errorBody}>
        <p className={styles.errorTitle}>{title}</p>
        {description && <p className={styles.errorDescription}>{description}</p>}
        {children}
        {onRetry && (
          <Button size="sm" onClick={onRetry} icon={<Icon name="refresh" size={14} />}>
            Try again
          </Button>
        )}
      </div>
    </div>
  )
}
