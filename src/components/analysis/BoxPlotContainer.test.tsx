import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BoxPlotContainer from './BoxPlotContainer'
import { unknownGeneMessage } from './geneInput'

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
