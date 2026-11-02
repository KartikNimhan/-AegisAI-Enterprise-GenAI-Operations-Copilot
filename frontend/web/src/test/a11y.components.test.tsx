/**
 * Component-level accessibility tests (M10.0) for the pieces whose states are hard to reach
 * through a page: chat messages in each state, the composer, the uploader and shared components.
 * Each test checks concrete requirements (names, roles, states), not only "axe found nothing".
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Composer } from '../components/Chat/Composer'
import { MessageBubble } from '../components/Chat/MessageBubble'
import { Uploader } from '../components/Documents/Uploader'
import { EmptyState } from '../components/EmptyState'
import { StatusBadge } from '../components/StatusBadge'
import type { ChatTurn } from '../types/chat'
import { expectAxe } from './axe'

const ALONE = { landmarks: false } as const

function turn(overrides: Partial<ChatTurn>): ChatTurn {
  return { id: 't1', role: 'assistant', content: '', ...overrides }
}

describe('Composer', () => {
  it('has a labelled message box and a named send button that is disabled until there is text', async () => {
    const { container } = render(<Composer onSend={vi.fn()} disabled={false} />)
    const box = screen.getByRole('textbox', { name: 'Message' })
    const send = screen.getByRole('button', { name: 'Send message' })
    expect(send).toBeDisabled()

    await userEvent.type(box, 'hello')
    expect(send).toBeEnabled()
    await expectAxe(container, ALONE)
  })
})

describe('MessageBubble', () => {
  it('announces the waiting state and marks the answer busy while it streams', async () => {
    const { container } = render(<MessageBubble turn={turn({ streaming: true })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Thinking…')
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull()
    await expectAxe(container, ALONE)
  })

  it('reports a failure as an alert and offers a named retry button', async () => {
    const onRetry = vi.fn()
    const { container } = render(
      <MessageBubble turn={turn({ content: 'Partial text', error: 'The model is unavailable.' })} onRetry={onRetry} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('The model is unavailable.')
    expect(screen.getByText('Partial text')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
    await expectAxe(container, ALONE)
  })

  it('labels the list of sources and the list of tools used', async () => {
    const { container } = render(
      <MessageBubble
        turn={turn({
          content: 'Answer [S1]',
          sources: [
            { source_id: 'S1', document_id: 'd1', filename: 'policy.pdf', chunk_index: 0, page: 2, similarity: 0.8, cited: true },
          ],
          toolSteps: [{ name: 'search_knowledge_base', status: 'succeeded' }],
        })}
      />,
    )
    expect(screen.getByRole('list', { name: 'Sources' })).toHaveTextContent('policy.pdf · page 2')
    expect(screen.getByRole('list', { name: 'Tools used' })).toHaveTextContent('search_knowledge_base')
    await expectAxe(container, ALONE)
  })
})

describe('Uploader', () => {
  it('is a keyboard-focusable control with a name and opens the file picker on Enter', async () => {
    const { container } = render(<Uploader onUploaded={vi.fn()} />)
    const dropzone = screen.getByRole('button', { name: /click to upload/i })
    expect(dropzone).toHaveAttribute('tabindex', '0')

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const click = vi.spyOn(input, 'click')
    dropzone.focus()
    await userEvent.keyboard('{Enter}')
    expect(click).toHaveBeenCalled()
    await expectAxe(container, ALONE)
  })
})

describe('Shared components', () => {
  it('EmptyState shows its title, description and action', async () => {
    const { container } = render(
      <EmptyState title="No documents yet" description="Upload a file." action={<button type="button">Upload</button>} />,
    )
    expect(screen.getByText('No documents yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload' })).toBeInTheDocument()
    await expectAxe(container, ALONE)
  })

  it.each([
    ['healthy', 'Healthy'],
    ['degraded', 'Degraded'],
    ['unavailable', 'Unavailable'],
    ['unknown', 'Unknown'],
  ] as const)('StatusBadge "%s" states its meaning in text, not colour alone', async (tone, label) => {
    const { container } = render(<StatusBadge tone={tone} />)
    expect(container).toHaveTextContent(label)
    await expectAxe(container, ALONE)
  })
})
