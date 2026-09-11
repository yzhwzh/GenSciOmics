import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BoxPlotContainer from './BoxPlotContainer'
import { unknownGeneMessage } from './geneInput'
import { BOXPLOT_GENE_KEY, storedGeneKey } from './useStoredGene'

// Mock child components
vi.mock('./PlotImage', () => ({ default: () => <div data-testid="plot-image">Plot</div> }))
vi.mock('./DetailTable', () => ({ default: () => <div data-testid="detail-table">Table</div> }))
vi.mock('./MuTestTable', () => ({ default: () => <div data-testid="mutest-table">MU</div> }))
vi.mock('./DragHandle', () => {
  const Drag = ({ onDrag }: { onDrag?: (d: number) => void }) => (
    <div data-testid="drag-handle" onClick={() => onDrag?.(10)}>Drag</div>
  )
  return { default: Drag }
})

// Mock API
vi.mock('../../api/analysis', () => ({
  searchGenes: vi.fn(() => Promise.resolve(['EGFR', 'EGF', 'EGR1', 'EGFL7'])),
}))

describe('BoxPlotContainer — Gene Input', () => {
  // Gene selection persists to sessionStorage — clear it so tests stay isolated.
  // Both ends: a leftover value from a previous test would seed the initial
  // state and quietly invalidate the placeholder assertions below.
  beforeEach(() => { try { sessionStorage.clear() } catch { /* ignore */ } })
  afterEach(() => { try { sessionStorage.clear() } catch { /* ignore */ } })

  it('renders gene input with placeholder from selectedGene', () => {
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')
    expect(input).toBeInTheDocument()
  })

  it('shows gene suggestions as user types', async () => {
    const user = userEvent.setup()
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')
    await user.type(input, 'EG')
    const suggestion = await screen.findByText('EGFR')
    expect(suggestion).toBeInTheDocument()
  })

  it('selects gene on Enter key press', async () => {
    const user = userEvent.setup()
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')

    await user.type(input, 'EGFR')
    await user.keyboard('{Enter}')

    // The placeholder mirrors selectedGene, so it is the only thing here that
    // can tell "committed" from "did nothing". Asserting on the plot instead
    // was vacuous: it renders whenever realPath is set, whatever gene is picked.
    expect(await screen.findByPlaceholderText('EGFR')).toBeInTheDocument()
  })

  it('selects gene on blur when input has text', async () => {
    const user = userEvent.setup()
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')

    await user.type(input, 'EGFR')
    await user.click(screen.getByTestId('plot-image'))

    expect(await screen.findByPlaceholderText('EGFR')).toBeInTheDocument()
  })

  // Regression — BUG_LOG B28. The mocked list holds EGFR, EGF, EGR1, EGFL7 and
  // the live dataset holds COL1A1 next to COL16A1, so a typed prefix used to be
  // substring-resolved by the backend into a real gene and reported as resolved.
  it('refuses a typed prefix on Enter instead of resolving it by substring', async () => {
    const user = userEvent.setup()
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')

    await user.type(input, 'EG')
    await user.keyboard('{Enter}')

    expect(screen.queryByPlaceholderText('FAP')).not.toBeNull()  // nothing committed
    expect(input).toHaveValue('EG')                              // left for the user to fix
  })

  // Blur is the wider entrance of the two — clicking anywhere else commits, so
  // the user never has to press Enter at all.
  it('refuses a typed prefix on blur', async () => {
    const user = userEvent.setup()
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')

    await user.type(input, 'EG')
    await user.click(screen.getByTestId('plot-image'))

    expect(screen.queryByPlaceholderText('FAP')).not.toBeNull()
    expect(input).toHaveValue('EG')
  })

  it('stores the canonical spelling when a real gene is typed in another case', async () => {
    const user = userEvent.setup()
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')

    await user.type(input, 'egfr')
    await user.keyboard('{Enter}')

    expect(await screen.findByPlaceholderText('EGFR')).toBeInTheDocument()
  })

  it('says so when the typed text is not a gene in this dataset', async () => {
    const user = userEvent.setup()
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')

    await user.type(input, 'NOTAGENE')
    await user.keyboard('{Enter}')

    // Read from the same constant the component renders, so a reworded message
    // cannot leave this assertion quietly matching nothing.
    expect(await screen.findByText(unknownGeneMessage('NOTAGENE'))).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('FAP')).not.toBeNull()
  })
})

/**
 * Regression — BUG_LOG B34. The gene box remembered one gene for the whole app
 * rather than one per dataset, so a value written by an older build (before B28
 * guarded the commit path) was read straight back and plotted: "CD3" is not in
 * the dataset, and the backend resolved it by substring into ABCD3. Reached
 * through the placeholder, because that is the only thing here that reflects
 * which gene was actually selected.
 */
describe('BoxPlotContainer — the remembered gene belongs to one dataset', () => {
  beforeEach(() => { try { sessionStorage.clear() } catch { /* ignore */ } })
  afterEach(() => { try { sessionStorage.clear() } catch { /* ignore */ } })

  it('ignores a gene stored under the old unscoped key', () => {
    try { sessionStorage.setItem(BOXPLOT_GENE_KEY, 'CD3') } catch { /* ignore */ }
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    expect(screen.queryByPlaceholderText('CD3')).toBeNull()
    expect(screen.getByPlaceholderText('FAP')).toBeInTheDocument()
  })

  it('restores a gene stored for this dataset', () => {
    try { sessionStorage.setItem(storedGeneKey(BOXPLOT_GENE_KEY, '/test/path.h5ad'), 'EGFR') } catch { /* ignore */ }
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    expect(screen.getByPlaceholderText('EGFR')).toBeInTheDocument()
  })

  // The leak that needed no stale data at all: pick a gene on dataset A, open
  // dataset B, and B used to restore A's gene and plot it unprompted.
  it("does not restore a gene stored for another dataset", () => {
    try { sessionStorage.setItem(storedGeneKey(BOXPLOT_GENE_KEY, '/other/dataset.h5ad'), 'EGFR') } catch { /* ignore */ }
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    expect(screen.queryByPlaceholderText('EGFR')).toBeNull()
    expect(screen.getByPlaceholderText('FAP')).toBeInTheDocument()
  })
})
