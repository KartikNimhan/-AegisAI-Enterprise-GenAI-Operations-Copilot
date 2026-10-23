import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PREVIEW_ROUTES, previewAllowed, previewRoute } from './guard'
import { installPreviewApi, previewReply, type PreviewTarget } from './mockApi'
import { mockAnswerFor } from './mockData'
import { PreviewApp } from './PreviewApp'

// UI tests that type a question and wait for a streamed answer are slower when the whole suite
// runs in parallel, so they get explicit, generous limits instead of the 1 s / 5 s defaults.
const UI_WAIT = { timeout: 15_000 }
const UI_TEST_TIMEOUT = 30_000

describe('previewAllowed', () => {
  it('requires development mode AND a local host', () => {
    expect(previewAllowed(true, 'localhost')).toBe(true)
    expect(previewAllowed(true, '127.0.0.1')).toBe(true)
    expect(previewAllowed(false, 'localhost')).toBe(false) // a production build
    expect(previewAllowed(true, 'example.com')).toBe(false) // served to someone else
    expect(previewAllowed(true, '192.168.1.20')).toBe(false)
    expect(previewAllowed(true, '')).toBe(false)
  })

  it('opens a known page from ?route= and ignores anything else', () => {
    expect(previewRoute('?route=/documents')).toBe('/documents')
    expect(previewRoute('')).toBe('/')
    expect(previewRoute('?route=https://evil.example/')).toBe('/')
    expect(previewRoute('?route=/api/v1/documents')).toBe('/')
    for (const route of PREVIEW_ROUTES) expect(previewRoute(`?route=${route}`)).toBe(route)
  })
})

describe('the mock API never reaches the network', () => {
  function fakeTarget() {
    const realFetch = vi.fn()
    const target = { fetch: realFetch, XMLHttpRequest: class {} } as unknown as PreviewTarget
    return { target, realFetch }
  }

  it('answers known reads from mock data and never calls the original fetch', async () => {
    const { target, realFetch } = fakeTarget()
    const restore = installPreviewApi(target)

    const response = await target.fetch('http://localhost:8000/api/v1/documents?limit=100')
    const body = await response.json()

    expect(response.status).toBe(200)
    expect(body.items[0].filename).toContain('[MOCK]')
    expect(realFetch).not.toHaveBeenCalled()
    restore()
    expect(target.fetch).toBe(realFetch) // fully restored
  })

  it('refuses unknown URLs, including other hosts, without calling the original fetch', async () => {
    const { target, realFetch } = fakeTarget()
    installPreviewApi(target)

    for (const url of [
      'http://localhost:8000/api/v1/auth/me',
      'https://evil.example/steal',
      '/api/v1/secret',
      'not a url at all',
    ]) {
      const response = await target.fetch(url)
      expect(response.status).toBe(404)
      expect((await response.json()).error.code).toBe('not_in_preview')
    }
    expect(realFetch).not.toHaveBeenCalled()
  })

  it('refuses every change as read-only', async () => {
    const { target, realFetch } = fakeTarget()
    installPreviewApi(target)

    for (const [method, url] of [
      ['DELETE', '/api/v1/documents/00000000-0000-4000-8000-000000000001'],
      ['POST', '/api/v1/memories'],
      ['PATCH', '/api/v1/memories/x'],
      ['DELETE', '/api/v1/memories'],
      ['POST', '/api/v1/documents/x/embeddings'],
    ]) {
      const response = await target.fetch(url, { method })
      expect(response.status).toBe(409)
      expect((await response.json()).error.code).toBe('preview_read_only')
    }
    expect(realFetch).not.toHaveBeenCalled()
  })

  it('ignores credentials entirely', async () => {
    const reply = previewReply('GET', '/api/v1/memories')
    expect(reply.status).toBe(200)
    expect(JSON.stringify(reply.body)).not.toMatch(/bearer|token|password|secret/i)
  })

  it('refuses a document upload without opening a connection', async () => {
    const { target } = fakeTarget()
    installPreviewApi(target)
    const xhr = new target.XMLHttpRequest()
    const loaded = new Promise<void>((resolve) => {
      xhr.onload = () => resolve()
    })

    xhr.open('POST', '/api/v1/documents')
    xhr.send(new FormData())
    await loaded

    expect(xhr.status).toBe(409)
    expect(JSON.parse(xhr.responseText).error.code).toBe('preview_read_only')
  })
})

describe('PreviewApp renders the real UI against mock data', () => {
  let restore: (() => void) | undefined
  afterEach(() => restore?.())

  function install() {
    restore = installPreviewApi(globalThis as unknown as PreviewTarget, { chunkDelayMs: 0 })
  }

  it('shows the preview badge, a signed-in mock user and the real navigation', async () => {
    install()
    render(<PreviewApp initialRoute="/documents" />)

    expect(screen.getByRole('note', { name: 'Preview mode' })).toHaveTextContent(/mock data/i)
    expect(await screen.findByText('[MOCK] Travel policy.pdf')).toBeInTheDocument()
    expect(screen.getByText('preview@example.invalid')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Memory' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Conversations' })).toBeInTheDocument()
  })

  it('navigates between pages with the existing sidebar', async () => {
    install()
    render(<PreviewApp />)

    await userEvent.click(screen.getByRole('link', { name: 'Memory' }))
    expect(await screen.findByText('[MOCK] Prefers short answers')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: 'Operations' }))
    expect(await screen.findByText('Total documents')).toBeInTheDocument()
  })

  it('answers a Copilot question with clearly labelled canned text', async () => {
    install()
    render(<PreviewApp />)

    await userEvent.type(screen.getByPlaceholderText(/ask the copilot/i), 'What is the travel policy?')
    await userEvent.click(screen.getByRole('button', { name: /send message/i }))

    await waitFor(() => expect(screen.getByText(/\[MOCK ANSWER\]/)).toBeInTheDocument(), UI_WAIT)
    expect(await screen.findByLabelText('Sources', {}, UI_WAIT)).toHaveTextContent(
      '[MOCK] Travel policy.pdf',
    )
  }, UI_TEST_TIMEOUT)

  it('shows the read-only message instead of pretending to save', async () => {
    install()
    render(<PreviewApp initialRoute="/memory" />)

    await userEvent.type(await screen.findByLabelText('New note'), 'a note')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/mock data, so changes are not saved/i)
  })
})

describe('simulated service status is never presented as real', () => {
  let restore: (() => void) | undefined
  afterEach(() => {
    restore?.()
    vi.useRealTimers()
  })

  function install() {
    restore = installPreviewApi(globalThis as unknown as PreviewTarget)
  }

  it('the mocked system status reports Unknown, never healthy', () => {
    const reply = previewReply('GET', '/api/v1/system/status')
    const body = reply.body as Record<string, unknown>

    expect(body.database).toBe('unknown')
    expect(body.redis).toBe('unknown')
    expect(body.llm_configured).toBe('unknown')
    expect(JSON.stringify(body)).not.toMatch(/"ok"|true|healthy/i)
  })

  it('System Status shows Unknown for the database, Redis and the LLM, and never Healthy', async () => {
    install()
    render(<PreviewApp initialRoute="/system" />)

    await waitFor(() => expect(screen.getAllByText('Unknown')).toHaveLength(3))
    expect(screen.queryByText('Healthy')).not.toBeInTheDocument()
    expect(screen.queryByText('Unavailable')).not.toBeInTheDocument()
    expect(screen.getAllByText('[MOCK] not checked').length).toBeGreaterThan(0)
  })

  it('the banner says on every page that status is simulated and nothing is connected', async () => {
    install()
    for (const route of ['/', '/system', '/documents']) {
      const { unmount } = render(<PreviewApp initialRoute={route} />)
      const banner = screen.getByRole('note', { name: 'Preview mode' })
      expect(banner).toHaveTextContent(/simulated/i)
      expect(banner).toHaveTextContent(/no backend, database or Redis is connected/i)
      expect(banner).toHaveTextContent(/nothing is saved/i)
      unmount()
    }
  })

  it('/health is never answered and never touches the real fetch', async () => {
    const realFetch = vi.fn()
    const target = { fetch: realFetch, XMLHttpRequest: class {} } as unknown as PreviewTarget
    installPreviewApi(target)

    expect(previewReply('GET', '/health').pending).toBe(true)
    const outcome = await Promise.race([
      target.fetch('/health').then(() => 'answered'),
      new Promise((resolve) => setTimeout(() => resolve('still waiting'), 50)),
    ])

    expect(outcome).toBe('still waiting')
    expect(realFetch).not.toHaveBeenCalled()
  })

  it('the top bar never claims the backend is connected or unreachable', async () => {
    vi.useFakeTimers()
    install()
    render(<PreviewApp />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000) // past the 30 s request timeout and several polls
    })

    expect(screen.getByText('Connecting…')).toBeInTheDocument()
    expect(screen.queryByText('Backend connected')).not.toBeInTheDocument()
    expect(screen.queryByText('Backend unreachable')).not.toBeInTheDocument()
  })
})

describe('canned answers depend on the question and are always labelled', () => {
  it('different questions get different answers, each starting with [MOCK ANSWER] and quoting it', () => {
    const questions = ['What is the travel policy?', 'How do I claim expenses?', 'What is the meaning of life?']
    const answers = questions.map((question) => mockAnswerFor(question))

    answers.forEach((answer, index) => {
      expect(answer.text.startsWith('[MOCK ANSWER]')).toBe(true)
      expect(answer.text).toContain(`You asked: "${questions[index]}"`)
      expect(answer.text).toContain('not a model response')
    })
    expect(new Set(answers.map((answer) => answer.text)).size).toBe(3)
    expect(answers[2].text).toContain('no canned answer for that topic')
  })

  it('cites the matching mock document only when the answer refers to one', () => {
    expect(mockAnswerFor('travel rules').sources.map((s) => s.filename)).toEqual([
      '[MOCK] Travel policy.pdf',
    ])
    expect(mockAnswerFor('expense receipts').sources.map((s) => s.filename)).toEqual([
      '[MOCK] Expense guidelines.docx',
    ])
    expect(mockAnswerFor('what do you remember about me').sources).toEqual([])
    expect(mockAnswerFor('random question').sources).toEqual([])
  })

  it('computes a simple calculation by pattern, never by evaluating code', () => {
    expect(mockAnswerFor('What is 250 * 0.18?').text).toContain('250 * 0.18 = 45')
    expect(mockAnswerFor('12 + 30').text).toContain('12 + 30 = 42')
    expect(mockAnswerFor('10 / 0').text).toContain('undefined (division by zero)')
    expect(mockAnswerFor('2 * 3').tool).toBe('calculator')
    // Something that only looks like code is just text: nothing runs.
    expect(mockAnswerFor('alert(); process.exit()').text).toContain('no canned answer')
  })

  it('shortens a very long question in the quote', () => {
    const answer = mockAnswerFor('x'.repeat(5000))
    expect(answer.text.length).toBeLessThan(400)
    expect(answer.text).toContain('…')
  })
})

describe('mock answers are streamed incrementally', () => {
  function target() {
    const realFetch = vi.fn()
    const t = { fetch: realFetch, XMLHttpRequest: class {} } as unknown as PreviewTarget
    return { t, realFetch }
  }

  async function readAll(response: Response) {
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let reads = 0
    let text = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      reads += 1
      text += decoder.decode(value)
    }
    return { reads, text }
  }

  /** The answer text carried by the frames' `delta` fields, joined back together. */
  function answerIn(raw: string): string {
    return raw
      .split('\n\n')
      .map((frame) => frame.split('\n').find((line) => line.startsWith('data: {')))
      .filter((line): line is string => Boolean(line))
      .map((line) => (JSON.parse(line.slice(6)) as { delta?: string }).delta ?? '')
      .join('')
  }

  const ask = (message: string, signal?: AbortSignal) => ({
    method: 'POST',
    body: JSON.stringify({ message }),
    signal,
  })

  it('sends the answer in many separate chunks, not one body', async () => {
    const { t, realFetch } = target()
    installPreviewApi(t, { chunkDelayMs: 1 })

    const { reads, text } = await readAll(
      await t.fetch('http://localhost:8000/api/v1/rag/chat/stream', ask('travel policy')),
    )

    expect(reads).toBeGreaterThan(10)
    expect(answerIn(text).startsWith('[MOCK ANSWER] You asked: "travel policy"')).toBe(true)
    expect(text).toContain('[MOCK] Travel policy.pdf') // in the final frame's sources
    expect(text.trim().endsWith('data: [DONE]')).toBe(true)
    expect(realFetch).not.toHaveBeenCalled()
  })

  it('stops when the request is aborted, like a real fetch', async () => {
    const { t } = target()
    installPreviewApi(t, { chunkDelayMs: 20 })
    const controller = new AbortController()
    const response = await t.fetch('/api/v1/rag/chat/stream', ask('travel', controller.signal))
    const reader = response.body!.getReader()

    await reader.read()
    controller.abort()

    await expect(reader.read()).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('plain chat neither cites nor lists sources', async () => {
    const { t } = target()
    installPreviewApi(t, { chunkDelayMs: 0 })

    const { text } = await readAll(
      await t.fetch('/api/v1/chat/completions/stream', ask('travel policy')),
    )

    expect(answerIn(text).startsWith('[MOCK ANSWER]')).toBe(true)
    expect(answerIn(text)).not.toMatch(/\[S\d+\]/)
    expect(text).not.toContain('[MOCK] Travel policy.pdf')
  })

  it('the agent stream reports the matching tool, then streams the answer in pieces', async () => {
    const { t } = target()
    installPreviewApi(t, { chunkDelayMs: 0 })

    const { text } = await readAll(await t.fetch('/api/v1/agents/run/stream', ask('What is 6 * 7?')))

    expect(text.indexOf('event: tool_started')).toBeLessThan(text.indexOf('event: answer_delta'))
    expect(text).toContain('"tool_name":"calculator"')
    expect(text.match(/event: answer_delta/g)!.length).toBeGreaterThan(5)
    expect(answerIn(text)).toContain('6 * 7 = 42')
    expect(text.trim().split('\n\n').pop()).toContain('event: completed')
  })

  it('the multi-agent workflow answers the question asked', async () => {
    const { t } = target()
    installPreviewApi(t)

    const response = await t.fetch('/api/v1/multi-agent/run', ask('How do I claim expenses?'))
    const body = await response.json()

    expect(body.answer).toContain('[MOCK ANSWER] You asked: "How do I claim expenses?"')
    expect(body.answer).toContain('mock expense guidelines')
  })

  it('a missing question just gets the fallback answer', () => {
    const reply = previewReply('POST', '/api/v1/rag/chat/stream', '')
    expect(answerIn(reply.sse!.join(''))).toContain('no canned answer')
  })
})

describe('the Copilot in preview mode', () => {
  let restore: (() => void) | undefined
  afterEach(() => restore?.())

  async function ask(question: string) {
    await userEvent.type(screen.getByPlaceholderText(/ask the copilot/i), question)
    await userEvent.click(screen.getByRole('button', { name: /send message/i }))
    await waitFor(() => expect(screen.getByPlaceholderText(/ask the copilot/i)).toBeEnabled(), UI_WAIT)
  }

  it('answers two different questions differently', async () => {
    restore = installPreviewApi(globalThis as unknown as PreviewTarget, { chunkDelayMs: 0 })
    render(<PreviewApp />)

    await ask('What is the travel policy?')
    await ask('What is 250 * 0.18?')

    expect(screen.getByText(/mock travel policy, economy fares/)).toBeInTheDocument()
    expect(screen.getByText(/250 \* 0\.18 = 45/)).toBeInTheDocument()
  }, UI_TEST_TIMEOUT)

  it('shows the question as plain text, never as markup', async () => {
    restore = installPreviewApi(globalThis as unknown as PreviewTarget, { chunkDelayMs: 0 })
    const { container } = render(<PreviewApp />)

    await ask('<img src=x onerror=alert()>')

    expect(container.querySelector('img')).toBeNull()
    expect(screen.getAllByText(/<img src=x onerror=alert\(\)>/).length).toBeGreaterThan(0)
  }, UI_TEST_TIMEOUT)

  it('agent mode shows the tool it chose for the question', async () => {
    restore = installPreviewApi(globalThis as unknown as PreviewTarget, { chunkDelayMs: 0 })
    render(<PreviewApp />)
    await userEvent.selectOptions(screen.getByLabelText(/answer mode/i), 'agent')

    await ask('What is 6 * 7?')

    expect(screen.getByLabelText('Tools used')).toHaveTextContent('calculator — done')
    expect(screen.getByText(/6 \* 7 = 42/)).toBeInTheDocument()
  }, UI_TEST_TIMEOUT)

  it('Stop interrupts an answer that is still arriving', async () => {
    restore = installPreviewApi(globalThis as unknown as PreviewTarget, { chunkDelayMs: 50 })
    render(<PreviewApp />)

    await userEvent.type(screen.getByPlaceholderText(/ask the copilot/i), 'travel policy')
    await userEvent.click(screen.getByRole('button', { name: /send message/i }))
    await userEvent.click(await screen.findByRole('button', { name: /stop generating/i }))

    expect(await screen.findByText('Stopped.', {}, UI_WAIT)).toBeInTheDocument()
    expect(screen.queryByText(/not a model response/)).not.toBeInTheDocument()
  }, UI_TEST_TIMEOUT)
})
