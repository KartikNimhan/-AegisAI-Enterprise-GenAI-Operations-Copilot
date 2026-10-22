import type { MultiAgentRunResult } from '../api/copilot'
import type { StreamSource } from '../api/stream'

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
  /** Sources the streamed answer was grounded in (arrive with the final chunk). */
  sources?: StreamSource[]
  /** The message this answer replies to, so a failed answer can be retried. */
  retryMessage?: string
  /** Tools the agent used for this answer, in order (agent mode). */
  toolSteps?: ToolStep[]
}

export interface ToolStep {
  name: string
  status: 'running' | 'succeeded' | 'failed'
}
