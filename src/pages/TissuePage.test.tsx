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

      // ...and a tick must actually repaint Processing -> Ready.
      //
      // Scope, stated honestly: this guards the wiring — that a tick reaches
      // setRows and the badge re-renders from it. It does NOT reproduce the
      // original caching bug, which needed the poll to hand React the *same
      // array reference* as current state so it bailed out. mockResolvedValue
      // returns one fixed array that differs from the load array, so no bailout
      // can occur here. Reference freshness rests entirely on apiFetch calling
      // res.json() per request, and nothing in this suite pins that down.
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(screen.queryAllByText(/Processing/).length).toBe(0)
      expect(screen.queryAllByText(/may be stale/i).length).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  // B30: when the source data is edited, the read can fail for a window and the
  // backend serves that row with all-zero counts. Printing those zeros next to a
  // green "Ready" badge makes a failed read look like a legitimately tiny dataset
  // — and because the poll only arms on `status !== 'ready'`, the zeros could
  // never heal on their own. 0 is a measurement; it must not be shown for a row
  // we could not read.
  it('renders an unreadable row as a failure rather than as 0 patients / Ready', async () => {
    fetchDatasetsMock.mockResolvedValue([
      dataset({ status: 'error', patient_count: 0, sample_count: 0, celltype_count: 0, n_obs: 0, group_dist: '' }),
    ] as never)

    render(<TissuePage />)

    await screen.findByText(/Read failed/i)
    expect(screen.queryByText('Ready')).toBeNull()
    expect(screen.queryByText('0')).toBeNull()
    expect(screen.queryAllByText('—').length).toBeGreaterThanOrEqual(3)
  })

  it('auto-recovers an unreadable row once the backend can read it again', async () => {
    vi.useFakeTimers()
    try {
      fetchDatasetsMock.mockResolvedValue([
        dataset({ status: 'error', patient_count: 0, sample_count: 0, celltype_count: 0 }),
      ] as never)
      // The next scan reads fine — same file, read succeeded.
      fetchDatasetsFreshMock.mockResolvedValue([dataset()] as never)

      render(<TissuePage />)
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(screen.queryAllByText(/Read failed/i).length).toBeGreaterThan(0)

      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(screen.queryAllByText(/Read failed/i).length).toBe(0)
      expect(screen.queryAllByText(/Ready/).length).toBeGreaterThan(0)
      expect(screen.queryAllByText('3').length).toBeGreaterThan(0)
    } finally {
      vi.useRealTimers()
    }
  })

  // The footer split is a deliverable, and mutation testing showed nothing
  // guarded it: deleting the "could not be read" span and relabelling error rows
  // "Processing…" again passed every other test in this file.
  it('calls an unreadable row unreadable in the footer, not "Processing"', async () => {
    fetchDatasetsMock.mockResolvedValue([dataset({ status: 'error', patient_count: 0 })] as never)

    render(<TissuePage />)

    await screen.findByText(/could not be read/i)
    // The old footer said this about every non-ready row, including unreadable ones.
    expect(screen.queryByText(/Processing/)).toBeNull()
  })

  // Counting over `rows` instead of what the table actually shows produced a
  // warning about a row the reader cannot see. The tab switch is the positive
  // control: same data, same footer, only the visible rows change.
  it('does not warn about an unreadable row that is not in the visible tab', async () => {
    fetchDatasetsMock.mockResolvedValue([
      dataset({ omics_type: 'BulkRNA', status: 'error', pmid: '11111111', patient_count: 0 }),
      dataset({ omics_type: 'scRNA', status: 'ready' }),
    ] as never)

    render(<TissuePage />)
    await screen.findByText('33936064')

    // Single Cell tab is active: the unreadable row is a Bulk RNA one.
    expect(screen.queryByText(/could not be read/i)).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: /Bulk RNA/i }))
    await screen.findByText(/could not be read/i)
  })

  // A literal 0 in the CSV survives into whatever downstream reads it, long
  // after the row has healed on screen. Mutation testing: reverting the
  // ternaries passed the whole suite.
  it('writes no zeros for an unreadable row in the CSV export', async () => {
    const captured: { blob: Blob | null } = { blob: null }
    URL.createObjectURL = vi.fn((b: Blob) => { captured.blob = b; return 'blob:mock' })
    URL.revokeObjectURL = vi.fn()
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    try {
      fetchDatasetsMock.mockResolvedValue([
        dataset({ status: 'error', patient_count: 0, sample_count: 0, celltype_count: 0, group_dist: '' }),
      ] as never)

      render(<TissuePage />)
      await screen.findByText(/Read failed/i)
      await userEvent.click(screen.getByRole('button', { name: /CSV/i }))

      const text = await captured.blob!.text()
      const fields = text.split('\n').find((l) => l.includes('33936064'))!.split(',')
      // Patient / Sample / CellTypes carry no measurement for this row.
      expect(fields.slice(5, 8)).toEqual(['-', '-', '-'])
    } finally {
      clickSpy.mockRestore()
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
