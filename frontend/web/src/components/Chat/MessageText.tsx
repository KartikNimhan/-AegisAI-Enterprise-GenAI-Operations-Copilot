/**
 * Safe rendering of model output (M10.3).
 *
 * The text is untrusted. It is NEVER parsed as HTML: there is no `dangerouslySetInnerHTML`, and
 * every piece becomes a React text node or one of a few fixed elements, so `<script>`, `<img
 * onerror>` or any other markup in an answer is shown as literal text. Links are not rendered (no
 * `javascript:` or other URL can ever become clickable).
 *
 * Supported, deliberately small: paragraphs (blank lines), line breaks, bulleted (`- `, `* `) and
 * numbered (`1. `) lists, `inline code` and **bold**. This replaces the planned `react-markdown`
 * renderer, whose installation was never authorized (see CLAUDE.md, M10 decision 9).
 *
 * Citation markers (`[S1]`, `[S1, S2]`) become buttons only for ids the BACKEND returned as
 * sources of this answer, and only when the saved answer can be opened (`onCitation`). Any other
 * marker stays plain text, so the UI never invents a source.
 */
import type { ReactNode } from 'react'
import styles from './MessageText.module.css'

const INLINE = /(\[S\d{1,3}(?:\s*,\s*S\d{1,3})*\]|`[^`\n]+`|\*\*[^*\n]+\*\*)/g
const BULLET = /^\s*[-*]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/

export interface MessageTextProps {
  text: string
  /** The source ids the backend returned for this answer. */
  sourceIds?: ReadonlySet<string>
  /** Opens a source; without it, markers are plain text (for example while still streaming). */
  onCitation?: (sourceId: string) => void
  /** Appended to the last block (the streaming cursor). */
  trailing?: ReactNode
}

function inline(
  text: string,
  key: string,
  sourceIds: ReadonlySet<string>,
  onCitation?: (sourceId: string) => void,
): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let n = 0
  for (const match of text.matchAll(INLINE)) {
    const token = match[0]
    const start = match.index ?? 0
    if (start > last) out.push(text.slice(last, start))
    last = start + token.length
    if (token.startsWith('`')) {
      out.push(<code key={`${key}-c${n++}`}>{token.slice(1, -1)}</code>)
    } else if (token.startsWith('**')) {
      out.push(<strong key={`${key}-b${n++}`}>{token.slice(2, -2)}</strong>)
    } else {
      const ids = token.slice(1, -1).split(',').map((id) => id.trim())
      const openable = onCitation && ids.every((id) => sourceIds.has(id))
      if (!openable) {
        out.push(token) // plain text: not a source this answer returned, or not openable yet
        continue
      }
      out.push(
        <span key={`${key}-s${n++}`} className={styles.citationGroup}>
          {ids.map((id) => (
            <button
              key={id}
              type="button"
              className={styles.citation}
              onClick={() => onCitation(id)}
              aria-label={`Open source ${id}`}
            >
              {id}
            </button>
          ))}
        </span>,
      )
    }
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function lines(
  block: string,
  key: string,
  sourceIds: ReadonlySet<string>,
  onCitation?: (sourceId: string) => void,
): ReactNode[] {
  return block.split('\n').flatMap((line, index) => [
    ...(index > 0 ? [<br key={`${key}-br${index}`} />] : []),
    ...inline(line, `${key}-${index}`, sourceIds, onCitation),
  ])
}

export function MessageText({ text, sourceIds = new Set(), onCitation, trailing }: MessageTextProps) {
  const blocks = text.split(/\n{2,}/).filter((block) => block.trim() !== '')
  if (blocks.length === 0) {
    return trailing ? <p className={styles.paragraph}>{trailing}</p> : null
  }
  return (
    <div className={styles.text}>
      {blocks.map((block, index) => {
        const key = `b${index}`
        const isLast = index === blocks.length - 1
        const rows = block.split('\n')
        const bullet = rows.every((row) => BULLET.test(row))
        const numbered = !bullet && rows.every((row) => NUMBERED.test(row))
        if (bullet || numbered) {
          const items = rows.map((row, i) => (
            <li key={`${key}-li${i}`}>
              {inline((bullet ? BULLET : NUMBERED).exec(row)?.[1] ?? row, `${key}-${i}`, sourceIds, onCitation)}
              {isLast && i === rows.length - 1 && trailing}
            </li>
          ))
          return bullet ? <ul key={key}>{items}</ul> : <ol key={key}>{items}</ol>
        }
        return (
          <p key={key} className={styles.paragraph}>
            {lines(block, key, sourceIds, onCitation)}
            {isLast && trailing}
          </p>
        )
      })}
    </div>
  )
}
