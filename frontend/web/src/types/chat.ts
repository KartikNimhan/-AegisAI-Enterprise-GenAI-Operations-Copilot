import type { MultiAgentRunResult } from '../api/copilot'

/**
 * A source an answer was grounded in, as the UI shows it. Built from a streamed source (always
 * available at answer time) or from a saved citation (resolved against the caller's CURRENT
 * access, so it may be unavailable). Only ids the backend returned ever become a SourceRef.
 */
export interface SourceRef {
  source_id: string
  cited: boolean
  filename: string | null
  page: number | null
  /** Absent for a live streamed source; "unavailable" hides every source detail. */
  status?: 'available' | 'unavailable'
  document_id?: string | null
  section?: string | null
  passage_truncated?: boolean
  /** Present on streamed sources (a `StreamSource` is a valid SourceRef). */
  chunk_index?: number | null
  chunk_id?: string
  similarity?: number
}

export interface ChatTurn {
  id: string
  role: 'user' | 'assistant'
  content: string
  result?: MultiAgentRunResult
  error?: string
  /** The answer is still arriving (streamed mode). */
  streaming?: boolean
  /** The user stopped the answer; `content` is whatever had arrived. */
  stopped?: boolean
  /** Sources the answer was grounded in (with the final chunk, or from the saved conversation). */
  sources?: SourceRef[]
  /** The saved assistant message (M10.4): citations are read through it once it exists. */
  messageId?: string
  /** The conversation the answer belongs to. */
  conversationId?: string
  /** Citation ids the model wrote that were not retrieved (they were removed from the text). */
  invalidCitations?: string[]
  /** The message this answer replies to, so a failed answer can be retried. */
  retryMessage?: string
  /** Tools the agent used for this answer, in order (agent mode). */
  toolSteps?: ToolStep[]
}

export interface ToolStep {
  name: string
  status: 'running' | 'succeeded' | 'failed'
}
