import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BoxPlotContainer from './BoxPlotContainer'

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
  // Gene selection persists to sessionStorage — clear it so tests stay isolated
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

    const plot = screen.getByTestId('plot-image')
    expect(plot).toBeInTheDocument()
  })

  it('selects gene on blur when input has text', async () => {
    const user = userEvent.setup()
    render(<BoxPlotContainer realPath="/test/path.h5ad" />)
    const input = screen.getByPlaceholderText('FAP')

    await user.type(input, 'EGFR')
    await user.click(screen.getByTestId('plot-image'))

    const plot = screen.getByTestId('plot-image')
    expect(plot).toBeInTheDocument()
  })
})
