import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import AggregateDetailTable from './AggregateDetailTable'
import { cachedFetch } from '../../api/client'

vi.mock('../../api/client', () => ({ cachedFetch: vi.fn() }))

const cachedFetchMock = vi.mocked(cachedFetch)

// Ungrouped view (conditionCol='None' → group_col=''), single cell type.
// Ungrouped column order in the rendered row:
//   0 Gene · 1 CellType · 2 Cell # · 3 Total Cells · 4 Ratio % · 5 Mean Expr. · 6 Expr. % · 7 Expr. #
interface MockRow {
  Gene: string
  CellType?: string
  Group?: string
  CellTypeNumber?: number
  CellTotalNumber?: number
  CellTypeRatio?: number
  GeneMeanExpression?: number | null
  GeneExpressionPct?: number
  GeneExpressionNumber?: number
}

// Spread via a named defaults object rather than inline literal properties: `Gene`
// is part of MockRow, so listing it before `...over` trips TS2783 ("specified more
// than once, so this usage will be overwritten") on `tsc -b`, which `npm run build` runs.
const ROW_DEFAULTS = {
  Gene: 'FAP',
  CellType: 'Macrophage',
  Group: '',
  CellTypeNumber: 1000,
  CellTotalNumber: 1000,
  CellTypeRatio: 100,
  GeneMeanExpression: 0,
  GeneExpressionPct: 0,
  GeneExpressionNumber: 0,
}

const row = (over: MockRow) => ({ ...ROW_DEFAULTS, ...over })

const singleGeneRows = [
  row({ Gene: 'FAP', GeneMeanExpression: 3.25, GeneExpressionPct: 45.5, GeneExpressionNumber: 455 }),
]

const fourGeneRows = [
  ...singleGeneRows,
  row({ Gene: 'COL1A1', GeneMeanExpression: 1.5, GeneExpressionPct: 30, GeneExpressionNumber: 300 }),
  // Boolean combo features carry no mean — backend emits GeneMeanExpression=null.
  row({ Gene: 'FAP | COL1A1', GeneMeanExpression: null, GeneExpressionPct: 65, GeneExpressionNumber: 650 }),
  row({ Gene: 'FAP & COL1A1', GeneMeanExpression: null, GeneExpressionPct: 20, GeneExpressionNumber: 200 }),
]

const lastUrl = (): string => {
  const calls = cachedFetchMock.mock.calls
  return String(calls[calls.length - 1]?.[0] ?? '')
}

describe('AggregateDetailTable — gene2 passthrough', () => {
  afterEach(() => {
    cachedFetchMock.mockReset()
  })

  it('case A: without gene2 the request URL has no gene2 param and only the primary gene renders', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: singleGeneRows as never,
      groups: [],
      fisher: { pairs: [], cell_types: [], matrix: [] },
    })
    render(<AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None" />)

    await screen.findByText('FAP')
    expect(lastUrl()).not.toContain('gene2=')
    expect(screen.queryByText('COL1A1')).toBeNull()
    expect(screen.queryByText('FAP | COL1A1')).toBeNull()
    expect(screen.queryByText('FAP & COL1A1')).toBeNull()
  })

  it('case B: with gene2 the URL carries gene2=COL1A1 and the gene2 + OR/AND combo rows render with blank Mean cells', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: fourGeneRows as never,
      groups: [],
      fisher: { pairs: [], cell_types: [], matrix: [] },
    })
    render(<AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None" gene2="COL1A1" />)

    // All four gene labels appear (they are distinct td text, so exact matches are unique).
    await screen.findByText('FAP | COL1A1')
    expect(screen.getByText('FAP')).toBeTruthy()
    expect(screen.getByText('COL1A1')).toBeTruthy()
    expect(screen.getByText('FAP & COL1A1')).toBeTruthy()
    expect(lastUrl()).toContain('gene2=COL1A1')

    // Real-gene rows carry a mean value; the OR/AND combo rows leave Mean Expr. blank.
    expect(screen.getAllByText('3.2500').length).toBe(1)
    expect(screen.getAllByText('1.5000').length).toBe(1)

    for (const comboGene of ['FAP | COL1A1', 'FAP & COL1A1']) {
      const tr = screen.getByText(comboGene).closest('tr')
      expect(tr).toBeTruthy()
      const cells = Array.from(tr!.querySelectorAll('td'))
      expect(cells[5].textContent).toBe('') // Mean Expr. blank for boolean combo features
      expect(cells[6].textContent).toBeTruthy() // Expr. % still populated
      expect(cells[7].textContent).toBeTruthy() // Expr. # still populated
    }
  })

  it('clearing gene2 refetches without the gene2 param (deps regression)', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: fourGeneRows as never,
      groups: [],
      fisher: { pairs: [], cell_types: [], matrix: [] },
    })
    const { rerender } = render(
      <AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None" gene2="COL1A1" />,
    )
    await screen.findByText('FAP | COL1A1')
    expect(lastUrl()).toContain('gene2=COL1A1')

    cachedFetchMock.mockResolvedValue({
      rows: singleGeneRows as never,
      groups: [],
      fisher: { pairs: [], cell_types: [], matrix: [] },
    })
    rerender(<AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None" gene2="" />)
    await waitFor(() => {
      expect(lastUrl()).not.toContain('gene2=')
    })
    expect(screen.queryByText('FAP | COL1A1')).toBeNull()
  })
})

describe('AggregateDetailTable — gene2_op passthrough + unresolved warning', () => {
  afterEach(() => {
    cachedFetchMock.mockReset()
  })

  const mergeRows = [
    row({ Gene: 'FAP', GeneMeanExpression: 3.25, GeneExpressionPct: 45.5, GeneExpressionNumber: 455 }),
    row({ Gene: 'COL1A1&COL1A2', GeneMeanExpression: null, GeneExpressionPct: 25, GeneExpressionNumber: 250 }),
  ]

  it('omits gene2_op by default so the URL stays byte-identical to the pre-feature client', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: mergeRows as never, groups: [], fisher: { pairs: [], cell_types: [], matrix: [] },
    })
    render(
      <AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None"
        gene2="COL1A1|COL1A2" gene2Label="M2" />,
    )

    await screen.findByText('COL1A1&COL1A2')
    expect(lastUrl()).toContain('gene2=COL1A1%7CCOL1A2')
    expect(lastUrl()).not.toContain('gene2_op')
  })

  it('sends gene2_op=and once the operator is applied', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: mergeRows as never, groups: [], fisher: { pairs: [], cell_types: [], matrix: [] },
    })
    render(
      <AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None"
        gene2="COL1A1|COL1A2" gene2Label="M2" gene2Op="and" />,
    )

    await screen.findByText('COL1A1&COL1A2')
    expect(lastUrl()).toContain('gene2_op=and')
  })

  it('never sends gene2_op without a gene2 to merge', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: singleGeneRows as never, groups: [], fisher: { pairs: [], cell_types: [], matrix: [] },
    })
    render(
      <AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None" gene2Op="and" />,
    )

    await screen.findByText('FAP')
    expect(lastUrl()).not.toContain('gene2_op')
  })

  it('warns about members that did not resolve, and does not render a banner when all resolved', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: mergeRows as never, groups: [], fisher: { pairs: [], cell_types: [], matrix: [] },
      gene2_resolved: [], gene2_unresolved: [],
    })
    const { rerender } = render(
      <AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None"
        gene2="COL1A1|COL1A2" gene2Op="and" />,
    )

    // Nothing missing → no permanent banner.
    await screen.findByText('COL1A1&COL1A2')
    expect(screen.queryByRole('status')).toBeNull()

    cachedFetchMock.mockResolvedValue({
      rows: mergeRows as never, groups: [], fisher: { pairs: [], cell_types: [], matrix: [] },
      gene2_resolved: ['COL1A1', 'COL1A2'], gene2_unresolved: ['NOPE'],
    })
    rerender(
      <AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None"
        gene2="COL1A1|NOPE|COL1A2" gene2Op="and" />,
    )

    const banner = await screen.findByRole('status')
    expect(banner.textContent).toContain('NOPE')
    expect(banner.textContent).toContain('2 个基因取交集')
  })

  it('warns about the degenerate single-member fallback, which is not a merge at all', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: mergeRows as never, groups: [], fisher: { pairs: [], cell_types: [], matrix: [] },
      gene2_resolved: ['COL1A1'], gene2_unresolved: ['NOPE'],
    })
    render(
      <AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None"
        gene2="NOPE|COL1A1" gene2Op="and" />,
    )

    const banner = await screen.findByRole('status')
    expect(banner.textContent).toContain('已退化为单基因 COL1A1')
  })

  it('still shows the warning when the table itself has no rows', async () => {
    cachedFetchMock.mockResolvedValue({
      rows: [], groups: [], fisher: { pairs: [], cell_types: [], matrix: [] },
      gene2_resolved: ['COL1A1'], gene2_unresolved: ['NOPE'],
    })
    render(
      <AggregateDetailTable realPath="/d/a.h5ad" gene="FAP" conditionCol="None"
        gene2="NOPE|COL1A1" gene2Op="and" />,
    )

    // The early "No data" return must not swallow the warning.
    await screen.findByText('No data')
    expect(screen.getByRole('status').textContent).toContain('NOPE')
  })
})
