import type { MultiAgentRunResult } from '../api/copilot'

export interface ChatTurn {
  id: string
  role: 'user' | 'assistant'
  content: string
  result?: MultiAgentRunResult
  error?: string
}
