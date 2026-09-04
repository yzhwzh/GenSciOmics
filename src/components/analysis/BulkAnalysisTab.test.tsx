import { describe, it, expect, vi, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BulkAnalysisTab from './BulkAnalysisTab'
import { searchGenes, fetchBulkBoxplot } from '../../api/analysis'

// Mock API layer — BulkAnalysisTab fetches on mount
vi.mock('../../api/analysis', () => ({
  searchGenes: vi.fn(() => Promise.resolve([])),
  fetchBulkDiseases: vi.fn(() => Promise.resolve(['RA', 'COPD'])),
  fetchBulkGroups: vi.fn(() => Promise.resolve(['G1', 'G2'])),
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
    expect(selects[2]).toHaveValue('All') // Target select defaults to All

    // [0] = gene input, [1] = case group, [2] = control group
    const inputs = screen.getAllByRole('textbox')
    expect(inputs[1]).toHaveValue('Tumor')
    expect(inputs[2]).toHaveValue('Normal')
  })

  it('persists a changed Target group selection to sessionStorage', async () => {
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    await user.selectOptions(screen.getAllByRole('combobox')[2], 'G1')
    expect(sessionStorage.getItem('gensci_bulk_target')).toBe('G1')
  })

  it('persists a changed disease selection to sessionStorage', async () => {
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    await user.selectOptions(screen.getAllByRole('combobox')[0], 'COPD')
    expect(sessionStorage.getItem('gensci_bulk_disease')).toBe('COPD')
  })

  it('selects a gene on suggestion mouseDown (regression: onBlur swallowed onClick)', async () => {
    vi.mocked(searchGenes).mockResolvedValue(['TP53', 'TPM2'])
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    const geneInput = screen.getAllByRole('textbox')[0] // [0] = gene, [1] = case, [2] = control
    await user.type(geneInput, 'TP')
    const tp53 = await screen.findByRole('button', { name: 'TP53' }) // debounced suggestions

    fireEvent.mouseDown(tp53) // new handler: preventDefault + select
    fireEvent.blur(geneInput) // simulate the browser focus-move that used to swallow the click
    fireEvent.click(tp53) // no-op on old code (button already unmounted)

    expect(geneInput).toHaveAttribute('placeholder', 'TP53') // gene box shows full gene
    expect(screen.queryByRole('button', { name: 'TP53' })).toBeNull() // dropdown closed
  })

  // ─── Show-Groups chips (subset display: which groups appear on the x-axis) ───
  // fetchBulkBoxplot(realPath, gene, disease?, palette, targetGroup?, groups?)
  const boxplotGroupsArg = (): string[] | undefined => {
    const calls = vi.mocked(fetchBulkBoxplot).mock.calls
    return calls[calls.length - 1]?.[5]
  }

  it('sends no groups param when all groups are shown (default)', async () => {
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results') // flush mount-time effects + group fetch
    expect(boxplotGroupsArg()).toBeUndefined()
  })

  it('hiding a group chip refetches with a groups param that excludes it', async () => {
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    await user.click(screen.getByRole('button', { name: 'G1' })) // hide G1 → only G2 shown
    expect(boxplotGroupsArg()).toEqual(['G2'])
    expect(sessionStorage.getItem('gensci_bulk_hidegroups')).toBe('["G1"]')
    expect(screen.getByRole('button', { name: 'G1' }).title).toBe('Show') // off → re-show
    expect(screen.getByRole('button', { name: 'G2' }).title).toBe('Hide') // on
  })

  it('re-shows a hidden group chip and drops the groups param when all are shown again', async () => {
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    await user.click(screen.getByRole('button', { name: 'G1' })) // hide G1
    expect(boxplotGroupsArg()).toEqual(['G2'])
    await user.click(screen.getByRole('button', { name: 'G1' })) // re-show G1
    expect(boxplotGroupsArg()).toBeUndefined()
    expect(sessionStorage.getItem('gensci_bulk_hidegroups')).toBe('[]')
  })

  it('refuses to hide the last visible group (prevent-zero)', async () => {
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    await user.click(screen.getByRole('button', { name: 'G1' })) // now only G2 visible
    const callsBefore = vi.mocked(fetchBulkBoxplot).mock.calls.length
    await user.click(screen.getByRole('button', { name: 'G2' })) // try to hide the last one
    expect(sessionStorage.getItem('gensci_bulk_hidegroups')).toBe('["G1"]') // unchanged
    expect(vi.mocked(fetchBulkBoxplot).mock.calls.length).toBe(callsBefore) // no refetch
  })

  it('resets the hidden-group subset when the dataset changes', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<BulkAnalysisTab realPath="/dataset/a" />)
    await screen.findByText('No results')
    await user.click(screen.getByRole('button', { name: 'G1' }))
    expect(sessionStorage.getItem('gensci_bulk_hidegroups')).toBe('["G1"]')

    rerender(<BulkAnalysisTab realPath="/dataset/b" />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'G1' }).title).toBe('Hide') // shown again
    })
    expect(sessionStorage.getItem('gensci_bulk_hidegroups')).toBe('[]')
  })
})
