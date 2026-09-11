import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ResolvedGeneNotice from './ResolvedGeneNotice'
import { resolvedGeneMessage } from './geneInput'

/**
 * The notice's entire job is deciding *whether* to speak, so every case here is
 * about the guard, not the wording. It is the only line in the app that says
 * which gene is actually on screen (BUG_LOG B34), which makes a notice that
 * renders when it should not as harmful as one that never renders: a warning
 * attached to the wrong gene teaches the reader to skip it.
 */
describe('ResolvedGeneNotice', () => {
  it('says which gene was plotted when the backend substituted another', () => {
    render(<ResolvedGeneNotice asked="CD3" resolution={{ asked: 'CD3', resolved: 'ABCD3' }} />)
    expect(screen.getByText(resolvedGeneMessage('CD3', 'ABCD3'))).toBeInTheDocument()
  })

  // The box moved on after this plot was requested, so the resolution describes a
  // gene that is no longer in the box. Showing it would caption the current gene
  // with the previous one's result.
  it('says nothing when the resolution belongs to a gene the box has left behind', () => {
    render(<ResolvedGeneNotice asked="TP53" resolution={{ asked: 'CD3', resolved: 'ABCD3' }} />)
    expect(screen.queryByText(resolvedGeneMessage('CD3', 'ABCD3'))).toBeNull()
  })

  // A pure case difference is the box working correctly.
  it('says nothing when the backend agreed with the box', () => {
    render(<ResolvedGeneNotice asked="EGFR" resolution={{ asked: 'EGFR', resolved: 'EGFR' }} />)
    expect(screen.queryByText(/instead/)).toBeNull()
  })

  it('says nothing before any plot has been resolved', () => {
    render(<ResolvedGeneNotice asked="EGFR" resolution={null} />)
    expect(screen.queryByText(/instead/)).toBeNull()
  })

  it('says nothing for a response that predates the backend reporting the field', () => {
    render(<ResolvedGeneNotice asked="EGFR" resolution={{ asked: 'EGFR', resolved: '' }} />)
    expect(screen.queryByText(/instead/)).toBeNull()
  })
})
