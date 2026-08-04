import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ChatPanel from './ChatPanel'

describe('ChatPanel', () => {
  it('renders user messages', () => {
    render(<ChatPanel messages={[{ role: 'user', content: 'Hello' }]} loading={false} error={null} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })

  it('renders assistant messages', () => {
    render(<ChatPanel messages={[{ role: 'assistant', content: 'Done' }]} loading={false} error={null} />)
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('shows loading spinner', () => {
    render(<ChatPanel messages={[]} loading={true} error={null} />)
    expect(screen.getByText('Analyzing...')).toBeInTheDocument()
  })

  it('shows error', () => {
    render(<ChatPanel messages={[]} loading={false} error='API key required' />)
    expect(screen.getByText('API key required')).toBeInTheDocument()
  })
})
