import { useId } from 'react'
import { type ThemePreference, useThemePreference } from './theme'
import styles from './ThemeSwitch.module.css'

const OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

/** A native radio group, so keyboard use (arrow keys) and screen readers work without extra code. */
export function ThemeSwitch() {
  const [preference, choose] = useThemePreference()
  const name = useId()

  return (
    <fieldset className={styles.switch}>
      <legend className="visually-hidden">Theme</legend>
      {OPTIONS.map((option) => (
        <label key={option.value} className={styles.option}>
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={preference === option.value}
            onChange={() => choose(option.value)}
            className={styles.input}
          />
          <span className={styles.label}>{option.label}</span>
        </label>
      ))}
    </fieldset>
  )
}
