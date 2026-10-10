/**
 * A tiny, dependency-free icon set (inline SVG paths) — avoids pulling in
 * an icon library for ~8 glyphs. Each icon is 20x20, stroke-based, and
 * inherits color from `currentColor` so it follows the surrounding text.
 */

export type IconName =
  | 'chat'
  | 'documents'
  | 'operations'
  | 'status'
  | 'send'
  | 'upload'
  | 'trash'
  | 'refresh'
  | 'chevron-left'
  | 'chevron-right'
  | 'plus'
  | 'alert'

const PATHS: Record<IconName, string> = {
  chat: 'M4 4h16v11H9l-5 4v-4H4V4z',
  documents: 'M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v4h4',
  operations: 'M4 19V11M10 19V5M16 19v-7M4 19h16',
  status: 'M12 3a9 9 0 1 0 9 9M12 3v9l6 3',
  send: 'M4 11l16-7-7 16-2-7-7-2z',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  trash: 'M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v6M14 11v6',
  refresh: 'M4 4v6h6M20 20v-6h-6M4.5 15a8 8 0 0 0 14.3 2.8M19.5 9a8 8 0 0 0-14.3-2.8',
  'chevron-left': 'M14 5l-7 7 7 7',
  'chevron-right': 'M10 5l7 7-7 7',
  plus: 'M12 4v16M4 12h16',
  alert: 'M12 8v5M12 17h.01M10.3 3.9L2.7 17a1.5 1.5 0 0 0 1.3 2.3h16a1.5 1.5 0 0 0 1.3-2.3L13.7 3.9a1.5 1.5 0 0 0-2.6 0z',
}

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
