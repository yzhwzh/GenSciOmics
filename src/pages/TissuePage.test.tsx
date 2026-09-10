import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TissuePage from './TissuePage'
import { fetchDatasets, fetchDatasetsFresh } from '../api/datasets'

// vi.hoisted: the factory below is hoisted above ordinary module scope, so the
// router params have to be reachable from it before anything else runs.
const route = vi.hoisted(() => ({ slug: 'kidney' }))

// fetchDatasetsFresh must be mocked too, even by tests that never reach the
// poll: a missing export is `undefined`, so the failure would surface as a
// "fetchDatasetsFresh is not a function" crash inside a timer callback rather
// than as an assertion.
vi.mock('../api/datasets', () => ({ fetchDatasets: vi.fn(), fetchDatasetsFresh: vi.fn() }))
vi.mock('react-router-dom', () => ({
  useParams: () => ({ slug: route.slug }),
  useNavigate: () => vi.fn(),
}))
// The workspace chat pulls in the whole LLM panel; not under test here.
vi.mock('../components/analysis', () => ({ LiteratureTab: () => null }))

const fetchDatasetsMock = vi.mocked(fetchDatasets)
const fetchDatasetsFreshMock = vi.mocked(fetchDatasetsFresh)

const dataset = (over: Partial<Record<string, unknown>> = {}) => ({
  species: 'Human',
  tissue: 'Kidney',
  disease: 'IgAN',
  pmid: '33936064',
  omics_type: 'scRNA',
  status: 'ready',
  size_mb: 120,
  patient_count: 3,
  sample_count: 6,
  celltype_count: 14,
  group_dist: 'IgAN:3, Health:3',
  ...over,
})

/**
 * Regression guard for the bug where a backend that is down (or still scanning)
 * rendered as "No datasets found in kidney/" — a claim about the data, when the
 * truth was that the request failed. The two states must stay distinguishable.
 */
describe('TissuePage — load failure vs. genuinely empty tissue', () => {
  // Default the fresh fetch to "still empty" so a test that does not care about
  // the re-check still exercises the empty branch deterministically instead of
  // calling an un-stubbed mock.
  beforeEach(() => {
    fetchDatasetsFreshMock.mockResolvedValue([])
  })

  afterEach(() => {
    fetchDatasetsMock.mockReset()
    fetchDatasetsFreshMock.mockReset()
    sessionStorage.clear()
    route.slug = 'kidney'
  })

  it('reports a load failure instead of claiming the tissue has no datasets', async () => {
    fetchDatasetsMock.mockRejectedValue(new Error('HTTP 502'))

    render(<TissuePage />)

    await screen.findByText(/Failed to load datasets/)
    expect(screen.queryByText(/No datasets found/)).toBeNull()
  })

  it('offers a retry that recovers once the backend is back', async () => {
    fetchDatasetsMock.mockRejectedValueOnce(new Error('HTTP 502'))
    render(<TissuePage />)

    const retry = await screen.findByRole('button', { name: /retry/i })

    fetchDatasetsMock.mockResolvedValue([dataset()] as never)
    await userEvent.click(retry)

    await screen.findAllByText('IgAN')
    expect(screen.queryByText(/Failed to load datasets/)).toBeNull()
  })

  it('still says "No datasets found" when the request succeeded but returned nothing', async () => {
    fetchDatasetsMock.mockResolvedValue([])

    render(<TissuePage />)

    await screen.findByText(/No datasets found/)
    expect(screen.queryByText(/Failed to load datasets/)).toBeNull()
  })

  it('renders the single-cell table on success', async () => {
    fetchDatasetsMock.mockResolvedValue([dataset()] as never)

    render(<TissuePage />)

    // 'IgAN' shows up twice by design — once in the header subtitle, once in the row.
    await waitFor(() => expect(screen.getAllByText('IgAN').length).toBeGreaterThanOrEqual(2))
    expect(screen.getByText('33936064')).toBeTruthy()
  })

  it('ignores a response that arrives after navigating to a different tissue', async () => {
    let resolveKidney: (rows: unknown[]) => void = () => {}
    fetchDatasetsMock.mockImplementation((tissue?: string) =>
      tissue === 'kidney'
        ? new Promise((res) => { resolveKidney = res as (rows: unknown[]) => void })
        : Promise.resolve([dataset({ disease: 'IPF', pmid: '32832598' })] as never))

    const { rerender } = render(<TissuePage />)

    // Leave kidney for lung before kidney ever answers.
    route.slug = 'lung'
    rerender(<TissuePage />)
    await screen.findAllByText('IPF')

    // The abandoned request finally lands — it must not repaint the page.
    // Flushed with act, not waitFor: a waitFor here would run its callback
    // against the pre-update DOM and resolve immediately, passing even while
    // the stale row is being painted. It reads like a guard but guards nothing.
    await act(async () => { resolveKidney([dataset({ disease: 'IgAN', pmid: '33936064' })]) })
    expect(screen.queryAllByText('IgAN').length).toBe(0)
  })

  // Retry is the one user-reachable path that can start a load, and it is only
  // cancellable because it re-runs the effect rather than issuing the request
  // from the click handler. React drops an onClick's return value, so a handler
  // that called a loader directly would leave that request with no cleanup and
  // let it repaint whatever tissue the user navigated to meanwhile.
  it('cancels a retried request when the user navigates away mid-flight', async () => {
    fetchDatasetsMock.mockRejectedValueOnce(new Error('HTTP 502'))

    const { rerender } = render(<TissuePage />)
    const retry = await screen.findByRole('button', { name: /retry/i })

    let resolveKidney: (rows: unknown[]) => void = () => {}
    fetchDatasetsMock.mockImplementationOnce(
      () => new Promise((res) => { resolveKidney = res as (rows: unknown[]) => void })
    )
    await userEvent.click(retry)

    route.slug = 'lung'
    fetchDatasetsMock.mockResolvedValue([dataset({ disease: 'IPF', pmid: '32832598' })] as never)
    rerender(<TissuePage />)
    await screen.findAllByText('IPF')

    await act(async () => { resolveKidney([dataset({ disease: 'IgAN', pmid: '33936064' })]) })
    expect(screen.queryAllByText('IgAN').length).toBe(0)
  })

  // The backend answers [] for every list request until its initial filesystem
  // scan finishes, so an empty successful response is not yet a fact about the
  // data. Rendering it as "No datasets found" is the exact claim B29 is about.
  it('re-checks once before believing an empty result, so the scan window is not reported as absence', async () => {
    fetchDatasetsMock.mockResolvedValue([])
    // Same question asked fresh: by now the scan has finished.
    fetchDatasetsFreshMock.mockResolvedValue([dataset()] as never)

    render(<TissuePage />)

    await screen.findAllByText('IgAN')
    expect(screen.queryByText(/No datasets found/)).toBeNull()
  })

  it('reports absence only after the re-check also comes back empty', async () => {
    fetchDatasetsMock.mockResolvedValue([])
    fetchDatasetsFreshMock.mockResolvedValue([])

    render(<TissuePage />)

    await screen.findByText(/No datasets found/)
    expect(fetchDatasetsFreshMock).toHaveBeenCalled()
    // The empty state is not a dead end — the reader can re-ask without reload.
    expect(screen.getByRole('button', { name: /refresh/i })).toBeTruthy()
  })

  it('keeps the empty list when the re-check itself fails', async () => {
    // The first request succeeded, so the empty list is still the best answer
    // available; a failed re-check must not escalate it into a load error.
    fetchDatasetsMock.mockResolvedValue([])
    fetchDatasetsFreshMock.mockRejectedValue(new Error('HTTP 502'))

    render(<TissuePage />)

    await screen.findByText(/No datasets found/)
    expect(screen.queryByText(/Failed to load datasets/)).toBeNull()
  })

  it('clears the Processing badge once a poll tick returns updated statuses', async () => {
    vi.useFakeTimers()
    try {
      // The load path reports a pending dataset, so the poll arms...
      fetchDatasetsMock.mockResolvedValue([dataset({ status: 'processing' })] as never)
      fetchDatasetsFreshMock.mockResolvedValue([dataset({ status: 'ready' })] as never)

      render(<TissuePage />)
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(screen.queryAllByText(/Processing/).length).toBeGreaterThan(0)

      // ...and a tick must actually repaint Processing -> Ready. This is the
      // symptom that was reported: with a cached fetch the tick returned the
      // same array reference, React bailed out, and the badge never moved.
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(screen.queryAllByText(/Processing/).length).toBe(0)
      expect(screen.queryAllByText(/may be stale/i).length).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('warns that the counts may be stale once the status poll starts failing', async () => {
    vi.useFakeTimers()
    try {
      fetchDatasetsMock.mockResolvedValue([dataset({ status: 'processing' })] as never)
      fetchDatasetsFreshMock.mockRejectedValue(new Error('HTTP 502'))

      render(<TissuePage />)
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(screen.queryAllByText(/may be stale/i).length).toBe(0)

      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(screen.queryAllByText(/may be stale/i).length).toBeGreaterThan(0)
    } finally {
      vi.useRealTimers()
    }
  })
})
