/**
 * Mock data for the development-only UI preview (see `./README` in `dev-preview.tsx`).
 *
 * Everything here is invented. Names start with "[MOCK]" so nothing can be mistaken for real
 * data, and no value is a real id, address, token or credential.
 */

const WHEN = '2026-01-15T09:30:00Z'

export const MOCK_USER = {
  subject: 'preview-user',
  issuer: 'https://preview.invalid/mock',
  email: 'preview@example.invalid',
  name: 'Preview User',
}

export const MOCK_DOCUMENTS = [
  {
    id: '00000000-0000-4000-8000-000000000001',
    filename: '[MOCK] Travel policy.pdf',
    content_type: 'application/pdf',
    document_type: 'pdf',
    file_size: 184_320,
    status: 'processed',
    error_message: null,
    page_count: 6,
    character_count: 14_200,
    metadata: null,
    created_at: WHEN,
    updated_at: WHEN,
    processed_at: WHEN,
  },
  {
    id: '00000000-0000-4000-8000-000000000002',
    filename: '[MOCK] Expense guidelines.docx',
    content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    document_type: 'docx',
    file_size: 52_100,
    status: 'processing',
    error_message: null,
    page_count: null,
    character_count: null,
    metadata: null,
    created_at: WHEN,
    updated_at: WHEN,
    processed_at: null,
  },
  {
    id: '00000000-0000-4000-8000-000000000003',
    filename: '[MOCK] Broken scan.pdf',
    content_type: 'application/pdf',
    document_type: 'pdf',
    file_size: 9_800,
    status: 'failed',
    error_message: '[MOCK] The file could not be read.',
    page_count: null,
    character_count: null,
    metadata: null,
    created_at: WHEN,
    updated_at: WHEN,
    processed_at: null,
  },
]

export const MOCK_CHUNKS = [
  {
    id: '10000000-0000-4000-8000-000000000001',
    chunk_index: 0,
    content: '[MOCK] Employees may claim economy fares for trips under six hours.',
    character_count: 67,
    token_count: null,
    metadata: null,
    created_at: WHEN,
  },
  {
    id: '10000000-0000-4000-8000-000000000002',
    chunk_index: 1,
    content: '[MOCK] Hotel stays are reimbursed up to the published nightly cap.',
    character_count: 66,
    token_count: null,
    metadata: null,
    created_at: WHEN,
  },
]

export const MOCK_EMBEDDING_STATUS = {
  document_id: MOCK_DOCUMENTS[0].id,
  provider: 'local',
  model: '[MOCK] embedding-model',
  model_version: '1',
  dimension: 384,
  total_chunks: 2,
  embedded_chunks: 2,
  status: 'complete',
}

export const MOCK_OPERATIONS = {
  total_documents: MOCK_DOCUMENTS.length,
  documents_by_status: { processed: 1, processing: 1, failed: 1 },
}

// Nothing is checked in preview, so nothing is reported as healthy or unhealthy. The System Status
// page renders any value other than 'ok' / 'unavailable' / a boolean as "Unknown"; the type says
// `llm_configured` is a boolean, but the page only passes it to a function that accepts strings too.
export const MOCK_SYSTEM_STATUS = {
  database: 'unknown',
  redis: 'unknown',
  llm_configured: 'unknown',
  trusted_a2a_agents: ['[MOCK] not checked'],
  mcp_server: '[MOCK] not checked',
}

export const MOCK_CONVERSATIONS = [
  {
    id: '20000000-0000-4000-8000-000000000001',
    title: '[MOCK] What can I expense on a trip?',
    created_at: WHEN,
    updated_at: WHEN,
  },
  {
    id: '20000000-0000-4000-8000-000000000002',
    title: '[MOCK] Summarise the expense guidelines',
    created_at: WHEN,
    updated_at: WHEN,
  },
]

export const MOCK_CONVERSATION_MESSAGES = [
  { id: 'm1', role: 'user', content: '[MOCK] What can I expense on a trip?', model: null, input_tokens: null, output_tokens: null, total_tokens: null, created_at: WHEN },
  { id: 'm2', role: 'assistant', content: '[MOCK] Economy fares and capped hotel stays [S1].', model: null, input_tokens: null, output_tokens: null, total_tokens: null, created_at: WHEN },
]

export const MOCK_MEMORIES = [
  {
    id: '30000000-0000-4000-8000-000000000001',
    kind: 'preference',
    source: 'user',
    content: '[MOCK] Prefers short answers',
    created_at: WHEN,
    updated_at: WHEN,
    expires_at: '2026-04-15T09:30:00Z',
  },
  {
    id: '30000000-0000-4000-8000-000000000002',
    kind: 'fact',
    source: 'agent',
    content: '[MOCK] Works in the finance team',
    created_at: WHEN,
    updated_at: WHEN,
    expires_at: '2026-04-15T09:30:00Z',
  },
]

// -- canned answers ------------------------------------------------------------------------------
//
// The answer depends on the question only through this keyword table. Nothing is generated: every
// answer is fixed text that starts with "[MOCK ANSWER]", quotes the question back, and says it is
// not a model response.

export interface MockSource {
  source_id: string
  document_id: string
  filename: string
  chunk_index: number
  page: number | null
  similarity: number
  cited: boolean
}

export interface MockAnswer {
  text: string
  /** Mock documents the text cites as [S1]; empty when it cites nothing. */
  sources: MockSource[]
  /** The tool the mock agent "uses" for this answer. */
  tool: string
}

function sourceFor(document: (typeof MOCK_DOCUMENTS)[number], page: number | null): MockSource {
  return {
    source_id: 'S1',
    document_id: document.id,
    filename: document.filename,
    chunk_index: 0,
    page,
    similarity: 0.91,
    cited: true,
  }
}

interface Topic {
  pattern: RegExp
  line: string
  sources: MockSource[]
}

const TOPICS: Topic[] = [
  {
    pattern: /\b(travel|trip|flight|fare|hotel)/,
    line: 'In the mock travel policy, economy fares are reimbursed and hotel stays are capped [S1].',
    sources: [sourceFor(MOCK_DOCUMENTS[0], 2)],
  },
  {
    pattern: /\b(expense|receipt|reimburs|claim)/,
    line: 'The mock expense guidelines say each claim needs a receipt within 30 days [S1].',
    sources: [sourceFor(MOCK_DOCUMENTS[1], null)],
  },
  {
    pattern: /\b(memory|memories|remember|preference)/,
    line: 'The mock memory says you prefer short answers and work in the finance team.',
    sources: [],
  },
  {
    pattern: /\b(document|documents|upload|file|files|pdf)\b/,
    line: 'The mock library holds three documents: one processed, one still processing and one that failed.',
    sources: [],
  },
  {
    pattern: /^(hi|hello|hey)\b/,
    line: 'Hello! Ask about the mock travel or expense documents, or try a calculation such as 250 * 0.18.',
    sources: [],
  },
]

const FALLBACK =
  'The preview has no canned answer for that topic. Try asking about travel, expenses, documents, memory or a calculation.'

const MAX_QUOTED_CHARS = 120

function quote(question: string): string {
  const flat = question.split(/\s+/).join(' ').trim()
  return flat.length > MAX_QUOTED_CHARS ? `${flat.slice(0, MAX_QUOTED_CHARS - 1)}…` : flat
}

const CALCULATION = /(-?\d+(?:\.\d+)?)\s*([+\-*/x×])\s*(-?\d+(?:\.\d+)?)/

/** `a op b` with two numbers, matched by a fixed pattern. Nothing is evaluated as code. */
function calculate(question: string): string | null {
  const match = CALCULATION.exec(question)
  if (!match) return null
  const [, left, op, right] = match
  const a = Number(left)
  const b = Number(right)
  let result: number
  if (op === '+') result = a + b
  else if (op === '-') result = a - b
  else if (op === '/') {
    if (b === 0) return `${left} / ${right} is undefined (division by zero), computed by the preview, not a model.`
    result = a / b
  } else result = a * b
  const rounded = Number(result.toFixed(6))
  return `${left} ${op} ${right} = ${rounded}, computed by the preview, not a model.`
}

/** The canned answer for `question`. Pure: the same question always gets the same answer. */
export function mockAnswerFor(question: string): MockAnswer {
  const asked = `[MOCK ANSWER] You asked: "${quote(question)}".`
  const tail = 'This is canned preview text, not a model response.'
  const calculation = calculate(question)
  if (calculation) return { text: `${asked} ${calculation} ${tail}`, sources: [], tool: 'calculator' }

  const lower = question.toLowerCase().trim()
  const topic = TOPICS.find((candidate) => candidate.pattern.test(lower))
  return {
    text: `${asked} ${topic ? topic.line : FALLBACK} ${tail}`,
    sources: topic ? topic.sources : [],
    tool: 'search_knowledge_base',
  }
}

export const MOCK_WORKFLOW_AGENTS = [
  {
    agent_name: 'research',
    capability: 'research',
    status: 'completed',
    error: null,
    duration_ms: 120,
    retry_count: 0,
  },
]
