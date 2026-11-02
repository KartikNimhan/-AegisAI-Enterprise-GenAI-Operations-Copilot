import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Composer } from './Composer'

describe('Composer', () => {
  it('caps the message at the length the API accepts', () => {
    render(<Composer onSend={vi.fn()} disabled={false} />)
    expect(screen.getByLabelText('Message')).toHaveAttribute('maxlength', '32000')
  })

  it('sends a trimmed message and ignores a blank one', async () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} disabled={false} />)
    const box = screen.getByLabelText('Message')

    await userEvent.type(box, '   {Enter}')
    expect(onSend).not.toHaveBeenCalled()

    await userEvent.type(box, '  hello  {Enter}')
    expect(onSend).toHaveBeenCalledWith('hello')
  })
})
