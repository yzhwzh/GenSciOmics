import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BulkAnalysisTab from './BulkAnalysisTab'

// Mock API layer — BulkAnalysisTab fetches on mount
vi.mock('../../api/analysis', () => ({
  searchGenes: vi.fn(() => Promise.resolve([])),
  fetchBulkDiseases: vi.fn(() => Promise.resolve(['RA', 'COPD'])),
  fetchBulkBoxplot: vi.fn(() => Promise.resolve({})),
  fetchBulkVolcano: vi.fn(() => Promise.resolve({})),
  fetchBulkDe: vi.fn(() => Promise.resolve({ genes: [], n_total: 0, n_tumor: 0, n_normal: 0 })),
}))

describe('BulkAnalysisTab — sessionStorage persistence (same pattern as scRNA)', () => {
  afterEach(() => { try { sessionStorage.clear() } catch { /* ignore */ } })

  it('restores persisted selections from sessionStorage on mount', async () => {
    try { sessionStorage.setItem('gensci_bulk_disease', 'RA') } catch { /* ignore */ }
    try { sessionStorage.setItem('gensci_bulk_case', 'Tumor') } catch { /* ignore */ }
    try { sessionStorage.setItem('gensci_bulk_control', 'Normal') } catch { /* ignore */ }
    try { sessionStorage.setItem('gensci_bulk_palette', 'pastel') } catch { /* ignore */ }

    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results') // flush mount-time fetch effects

    const selects = screen.getAllByRole('combobox')
    expect(selects[0]).toHaveValue('RA') // Disease select
    expect(selects[1]).toHaveValue('pastel') // Palette select

    // [0] = gene input, [1] = case group, [2] = control group
    const inputs = screen.getAllByRole('textbox')
    expect(inputs[1]).toHaveValue('Tumor')
    expect(inputs[2]).toHaveValue('Normal')
  })

  it('persists a changed disease selection to sessionStorage', async () => {
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    await user.selectOptions(screen.getAllByRole('combobox')[0], 'COPD')
    expect(sessionStorage.getItem('gensci_bulk_disease')).toBe('COPD')
  })
})
