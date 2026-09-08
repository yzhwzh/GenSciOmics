import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import FisherTable from './FisherTable'
import { cachedFetch } from '../../api/client'

vi.mock('../../api/client', () => ({ cachedFetch: vi.fn() }))

const cachedFetchMock = vi.mocked(cachedFetch)

const fisherPayload = (rows: { gene: string; pair?: string; pvals: (number | null)[] }[]) => ({
  rows: [],
  fisher: {
    cell_types: ['AT1', 'AT2'],
    rows: rows.map(r => ({ gene: r.gene, pair: r.pair ?? 'IPF_vs_Control', pvals: r.pvals })),
  },
})

const lastUrl = (): string => {
  const calls = cachedFetchMock.mock.calls
  return String(calls[calls.length - 1]?.[0] ?? '')
}

describe('FisherTable — gene2 passthrough + Gene column', () => {
  afterEach(() => {
    cachedFetchMock.mockReset()
  })

  it('case A: without gene2 the request URL has no gene2 param and the leading Gene column shows the primary gene', async () => {
    cachedFetchMock.mockResolvedValue(
      fisherPayload([{ gene: 'FAP', pvals: [0.0032, 0.512] }]) as never,
    )
    render(<FisherTable realPath="/d/a.h5ad" gene="FAP" conditionCol="Group" />)

    await screen.findByText('FAP')
    expect(lastUrl()).toContain('genes=FAP')
    expect(lastUrl()).not.toContain('gene2=')
    expect(screen.getAllByText('IPF vs Control').length).toBe(1)
    expect(screen.getByText('0.0032')).toBeTruthy()
    expect(screen.queryByText('COL1A1')).toBeNull()
  })

  it('case B: with gene2 the URL carries gene2 and all 4 feature labels appear in the Gene column', async () => {
    cachedFetchMock.mockResolvedValue(
      fisherPayload([
        { gene: 'FAP', pvals: [0.0032, 0.512] },
        { gene: 'COL1A1', pvals: [0.00004, 0.9999] },
        { gene: 'FAP | COL1A1', pvals: [0.01, null] },
        { gene: 'FAP & COL1A1', pvals: [0.000001, 0.2] },
      ]) as never,
    )
    render(<FisherTable realPath="/d/a.h5ad" gene="FAP" conditionCol="Group" gene2="COL1A1" />)

    // Leading Gene column lists every feature label emitted for this gene pair.
    await screen.findByText('FAP | COL1A1')
    expect(lastUrl()).toContain('gene2=COL1A1')
    expect(screen.getByText('FAP')).toBeTruthy()
    expect(screen.getByText('COL1A1')).toBeTruthy()
    expect(screen.getByText('FAP | COL1A1')).toBeTruthy()
    expect(screen.getByText('FAP & COL1A1')).toBeTruthy()
    // One visible row per gene × pair.
    expect(screen.getAllByText('IPF vs Control').length).toBe(4)
    // p-value formatting: tiny values collapse to '<0.001'; null renders '-'.
    expect(screen.getAllByText('<0.001').length).toBe(2)
    expect(screen.getAllByText('-').length).toBe(1)
  })

  it('clearing gene2 refetches without the gene2 param (deps regression)', async () => {
    cachedFetchMock.mockResolvedValue(
      fisherPayload([
        { gene: 'FAP', pvals: [0.0032] },
        { gene: 'COL1A1', pvals: [0.8] },
      ]) as never,
    )
    const { rerender } = render(
      <FisherTable realPath="/d/a.h5ad" gene="FAP" conditionCol="Group" gene2="COL1A1" />,
    )
    await screen.findByText('COL1A1')
    expect(lastUrl()).toContain('gene2=COL1A1')

    cachedFetchMock.mockResolvedValue(
      fisherPayload([{ gene: 'FAP', pvals: [0.0032] }]) as never,
    )
    rerender(<FisherTable realPath="/d/a.h5ad" gene="FAP" conditionCol="Group" gene2="" />)
    await waitFor(() => {
      expect(lastUrl()).not.toContain('gene2=')
    })
    expect(screen.queryByText('COL1A1')).toBeNull()
  })
})
