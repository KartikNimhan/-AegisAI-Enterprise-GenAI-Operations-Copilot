/** M10.3: safe rendering of model output, and citation markers that only open real sources. */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { expectAxe } from '../../test/axe'
import { MessageText } from './MessageText'

describe('MessageText', () => {
  it('shows markup in an answer as literal text, never as HTML', () => {
    const hostile =
      '<img src=x onerror="alert(1)"> <script>alert(2)</script> <a href="javascript:alert(3)">x</a>'
    const { container } = render(<MessageText text={hostile} />)

    expect(container.querySelector('img, script, a, iframe')).toBeNull()
    expect(container).toHaveTextContent('<img src=x onerror="alert(1)">')
    expect(container).toHaveTextContent('<script>alert(2)</script>')
  })

  it('renders paragraphs, line breaks, lists, inline code and bold', () => {
    const text = 'First line\nsecond line\n\n- one\n- two\n\n1. alpha\n2. beta\n\nUse `ls` and **care**.'
    const { container } = render(<MessageText text={text} />)

    expect(container.querySelectorAll('p')).toHaveLength(2)
    expect(container.querySelector('br')).not.toBeNull()
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['one', 'two', 'alpha', 'beta'])
    expect(container.querySelector('ul')).not.toBeNull()
    expect(container.querySelector('ol')).not.toBeNull()
    expect(container.querySelector('code')).toHaveTextContent('ls')
    expect(container.querySelector('strong')).toHaveTextContent('care')
  })

  it('turns markers of returned sources into buttons that open them', async () => {
    const onCitation = vi.fn()
    const user = userEvent.setup()
    const { container } = render(
      <MessageText text="Claim [S1] and both [S1, S2]." sourceIds={new Set(['S1', 'S2'])} onCitation={onCitation} />,
    )

    const buttons = screen.getAllByRole('button', { name: /open source/i })
    expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Open source S1',
      'Open source S1',
      'Open source S2',
    ])
    await user.click(buttons[2])
    expect(onCitation).toHaveBeenCalledWith('S2')
    await expectAxe(container)
  })

  it('leaves a marker the backend did not return as plain text', () => {
    render(<MessageText text="Only [S1] here, not [S9]." sourceIds={new Set(['S1'])} onCitation={vi.fn()} />)

    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(screen.getByText(/not \[S9\]\./)).toBeInTheDocument()
  })

  it('keeps every marker plain while the answer cannot be opened yet', () => {
    render(<MessageText text="Streaming [S1]." sourceIds={new Set(['S1'])} />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('Streaming [S1].')).toBeInTheDocument()
  })

  it('appends the trailing element to the last block', () => {
    const { container } = render(<MessageText text={'a\n\nb'} trailing={<span data-testid="cursor" />} />)

    expect(container.querySelectorAll('p')[1]).toContainElement(screen.getByTestId('cursor'))
  })
})
