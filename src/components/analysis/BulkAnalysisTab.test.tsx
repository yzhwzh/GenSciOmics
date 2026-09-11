import { describe, it, expect, vi, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BulkAnalysisTab from './BulkAnalysisTab'
import { searchGenes, fetchBulkBoxplot, fetchBulkAxes } from '../../api/analysis'
import { resolvedGeneMessage } from './geneInput'
import { BULK_GENE_KEY, storedGeneKey } from './useStoredGene'

// Mock API layer — BulkAnalysisTab fetches on mount
vi.mock('../../api/analysis', () => ({
  searchGenes: vi.fn(() => Promise.resolve([])),
  fetchBulkAxes: vi.fn(() => Promise.resolve({ diseases: ['RA', 'COPD'], tissueColumn: null })),
  fetchBulkGroups: vi.fn(() => Promise.resolve(['G1', 'G2'])),
  fetchBulkBoxplot: vi.fn(() => Promise.resolve({})),
  fetchBulkVolcano: vi.fn(() => Promise.resolve({})),
  fetchBulkDe: vi.fn(() => Promise.resolve({ genes: [], n_total: 0, n_tumor: 0, n_normal: 0 })),
}))

describe('BulkAnalysisTab — sessionStorage persistence (same pattern as scRNA)', () => {
  afterEach(() => {
    try { sessionStorage.clear() } catch { /* ignore */ }
    // Tests that fake a Tissue column restore the no-tissue default afterwards.
    vi.mocked(fetchBulkAxes).mockImplementation(() =>
      Promise.resolve({ diseases: ['RA', 'COPD'], tissueColumn: null }))
  })

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

  // ─── Panel X-axis segmented control (疾病 | 组织) ───
  // fetchBulkBoxplot(realPath, gene, disease?, palette, targetGroup?, groups?, xFactorCol?)
  const boxplotXFactorArg = (): string | undefined => {
    const calls = vi.mocked(fetchBulkBoxplot).mock.calls
    return calls[calls.length - 1]?.[6]
  }

  it('shows no tissue toggle when the dataset has no Tissue column', async () => {
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')
    expect(screen.queryByRole('button', { name: '组织' })).toBeNull()
    expect(screen.queryByRole('button', { name: '疾病' })).toBeNull()
  })

  it('switching the toggle to 组织 refetches the boxplot with the Tissue x-axis', async () => {
    vi.mocked(fetchBulkAxes).mockImplementation(() =>
      Promise.resolve({ diseases: ['RA', 'COPD'], tissueColumn: 'Tissue' }))
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    expect(boxplotXFactorArg()).toBeUndefined() // 疾病 (default) → param omitted
    await user.click(screen.getByRole('button', { name: '组织' }))
    expect(boxplotXFactorArg()).toBe('Tissue') // x_factor = obs column name
    expect(sessionStorage.getItem('gensci_bulk_xfactor')).toBe('Tissue')

    await user.click(screen.getByRole('button', { name: '疾病' }))
    expect(boxplotXFactorArg()).toBeUndefined() // back to Disease → omitted
    expect(sessionStorage.getItem('gensci_bulk_xfactor')).toBe('Disease')
  })

  it('choosing 组织 hides the boxplot Disease selector and resets it to All', async () => {
    vi.mocked(fetchBulkAxes).mockImplementation(() =>
      Promise.resolve({ diseases: ['RA', 'COPD'], tissueColumn: 'Tissue' }))
    const user = userEvent.setup()
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    // 4 selects: boxplot Disease/Palette/Target + the volcano card's Disease.
    const combos = () => screen.getAllByRole('combobox')
    expect(combos()).toHaveLength(4)
    await user.selectOptions(combos()[0], 'COPD') // pick a specific disease
    expect(combos()).toHaveLength(4) // 疾病 mode keeps the selector visible

    await user.click(screen.getByRole('button', { name: '组织' }))
    // Disease selector is meaningless in tissue mode → hidden (Palette/Target + volcano left).
    expect(combos()).toHaveLength(3)
    const calls = vi.mocked(fetchBulkBoxplot).mock.calls
    const last = calls[calls.length - 1]
    expect(last[2]).toBeUndefined() // disease reset to All → param omitted
    expect(last[6]).toBe('Tissue') // x_factor = tissue column

    await user.click(screen.getByRole('button', { name: '疾病' }))
    expect(combos()).toHaveLength(4) // selector restored...
    expect(combos()[0]).toHaveValue('All') // ...back to the all-disease default
  })
})

/**
 * Regression — BUG_LOG B34. Two things the gene box never did: scope its
 * remembered value to one dataset, and report a gene the backend substituted.
 *
 * The second matters more here than on the scRNA tabs. Their gene boxes go
 * through resolveGeneChoice, which refuses a name the dataset does not hold, so
 * a substitution there has to come from a stale stored value. This box has no
 * such guard — selectGene takes whatever was typed (:272) — so typing `COL1`
 * against TCGA really does chart COL10A1, and this line is the only thing that
 * says so.
 */
describe('BulkAnalysisTab — the remembered gene, and the one actually plotted', () => {
  afterEach(() => {
    try { sessionStorage.clear() } catch { /* ignore */ }
    vi.mocked(fetchBulkAxes).mockImplementation(() =>
      Promise.resolve({ diseases: ['RA', 'COPD'], tissueColumn: null }))
    vi.mocked(fetchBulkBoxplot).mockImplementation(() => Promise.resolve({}))
  })

  const geneInput = () => screen.getAllByRole('textbox')[0]

  it('ignores a gene stored under the old unscoped key', async () => {
    try { sessionStorage.setItem('gensci_bulk_gene', 'CD3') } catch { /* ignore */ }
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    expect(geneInput()).toHaveAttribute('placeholder', 'TP53')
  })

  it('restores a gene stored for this dataset', async () => {
    try { sessionStorage.setItem(storedGeneKey(BULK_GENE_KEY, '/test/path'), 'EGFR') } catch { /* ignore */ }
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    expect(geneInput()).toHaveAttribute('placeholder', 'EGFR')
  })

  it('says which gene it plotted when the backend substituted another', async () => {
    vi.mocked(fetchBulkBoxplot).mockImplementation(() =>
      Promise.resolve({ image: 'aGk=', gene_resolved: 'COL10A1' }))
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    // Read from the same helper the notice renders, so a reworded message cannot
    // leave this assertion quietly matching nothing.
    expect(await screen.findByText(resolvedGeneMessage('TP53', 'COL10A1'))).toBeInTheDocument()
  })

  it('stays silent when the backend plotted the gene that was asked for', async () => {
    vi.mocked(fetchBulkBoxplot).mockImplementation(() =>
      Promise.resolve({ image: 'aGk=', gene_resolved: 'TP53' }))
    render(<BulkAnalysisTab realPath="/test/path" />)
    await screen.findByText('No results')

    expect(screen.queryByText(resolvedGeneMessage('TP53', 'COL10A1'))).toBeNull()
  })
})
