import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Icon } from '../Icon'
import styles from './Composer.module.css'

export function Composer({
  onSend,
  disabled,
}: {
  onSend: (message: string) => void
  disabled: boolean
}) {
  const [value, setValue] = useState('')

  function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className={styles.composer}>
      <textarea
        className={styles.input}
        placeholder="Ask the Copilot…"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={1}
        aria-label="Message"
      />
      <button
        type="button"
        className={styles.send}
        onClick={submit}
        disabled={disabled || !value.trim()}
        aria-label="Send message"
      >
        <Icon name="send" size={18} />
      </button>
    </div>
  )
}
