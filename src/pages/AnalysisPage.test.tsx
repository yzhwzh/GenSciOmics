import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPage from './AnalysisPage'
import { findDataset } from '../api/datasets'
import { fetchAnalysisInfo, fetchAbstract, fetchUmapData } from '../api/analysis'

vi.mock('react-router-dom', () => ({
  useParams: () => ({ tissue: 'kidney', disease: 'IgAN', pmid: '33936064' }),
  useNavigate: () => vi.fn(),
}))
vi.mock('../api/datasets', () => ({ findDataset: vi.fn() }))
vi.mock('../api/analysis', () => ({
  fetchAnalysisInfo: vi.fn(),
  fetchAbstract: vi.fn(),
  fetchUmapData: vi.fn(),
}))
// The five tab bodies pull in ECharts, the LLM panel and the whole container
// tree; this suite is about the guard that runs before any of them.
vi.mock('../components/analysis', () => ({
  InfoPanel: () => null,
  UmapTabContent: () => null,
  BoxPlotContainer: () => null,
  ExpressionChartContainer: () => null,
  FreeAnalysisTab: () => null,
  BulkAnalysisTab: () => null,
}))

const findDatasetMock = vi.mocked(findDataset)
const fetchAnalysisInfoMock = vi.mocked(fetchAnalysisInfo)
const fetchAbstractMock = vi.mocked(fetchAbstract)
const fetchUmapDataMock = vi.mocked(fetchUmapData)

const ds = (over: Partial<Record<string, unknown>> = {}) => ({
  species: 'Human',
  tissue: 'Kidney',
  disease: 'IgAN',
  pmid: '33936064',
  omics_type: 'scRNA',
  status: 'ready',
  real_path: '/data/Human/Kidney/IgAN/33936064.IgAN.h5ad',
  patient_count: 3,
  ...over,
})

// One shared matcher. The two absence assertions below are only meaningful if
// this still matches what the page renders, so keeping all three uses on one
// constant is the point — a reworded message updates them together.
const READ_FAILED_RE = /could not read/i

/**
 * The tissue table disables the PMID link for a failed read, but the analysis
 * page is still reachable by hand-typed URL, bookmark or back button — and it
 * used to take `real_path` and load regardless. Every request it then makes
 * reads a file the scanner has already told us it cannot read.
 */
describe('AnalysisPage — a failed read must not open the analysis', () => {
  beforeEach(() => {
    findDatasetMock.mockReset()
    fetchAnalysisInfoMock.mockReset().mockResolvedValue({} as never)
    // `{}` 意味着 abstract_ready 是 undefined，页面据此判定摘要还要再取一次 ——
    // 所以这里必须给 fetchAbstract 一个 resolved 值，否则页面会调到未 mock 的路径。
    fetchAbstractMock.mockReset().mockResolvedValue({ pmid: '33936064', abstract: null, abstract_ready: false })
    fetchUmapDataMock.mockReset().mockResolvedValue({} as never)
  })

  it('stops before loading anything for a dataset whose read failed', async () => {
    findDatasetMock.mockResolvedValue(ds({ status: 'error', patient_count: 0, n_obs: 0 }) as never)

    render(<AnalysisPage />)

    await screen.findByText(READ_FAILED_RE)
    // The load-bearing assertion: no analysis request was issued against a file
    // the scanner already failed to read.
    expect(fetchAnalysisInfoMock).not.toHaveBeenCalled()
  })

  it('offers a retry that opens the analysis once the read succeeds', async () => {
    findDatasetMock.mockResolvedValueOnce(ds({ status: 'error' }) as never)

    render(<AnalysisPage />)
    const retry = await screen.findByRole('button', { name: /retry/i })

    findDatasetMock.mockResolvedValue(ds() as never)
    await userEvent.click(retry)

    await waitFor(() => expect(fetchAnalysisInfoMock).toHaveBeenCalled())
    expect(screen.queryByText(READ_FAILED_RE)).toBeNull()
    // The tab bar only exists past the guard; 'Study Info' is both a tab label
    // and a section heading, so match the button rather than the bare text.
    expect(await screen.findByRole('button', { name: /study info/i })).toBeTruthy()
  })

  // Non-error statuses are refused too. This is the user's original symptom:
  // data is being written, the scanner lists the row, and every request against
  // it returns zeros that look like real counts.
  it('stops before loading anything for a dataset that is still importing', async () => {
    findDatasetMock.mockResolvedValue(ds({ status: 'importing' }) as never)

    render(<AnalysisPage />)

    await screen.findByText(/still being imported/i)
    expect(fetchAnalysisInfoMock).not.toHaveBeenCalled()
  })

  // A missing row is a dead end, not a transient failure — offering Retry would
  // invite the reader to click forever.
  it('does not offer a retry when there is no such dataset', async () => {
    findDatasetMock.mockResolvedValue(null)

    render(<AnalysisPage />)

    await screen.findByText(/dataset not found/i)
    expect(screen.queryByRole('button', { name: /retry/i })).toBeNull()
  })

  // Positive control: without this, the tests above would also pass if the page
  // had simply stopped loading anything at all.
  it('opens the analysis normally for a readable dataset', async () => {
    findDatasetMock.mockResolvedValue(ds() as never)

    render(<AnalysisPage />)

    await waitFor(() =>
      expect(fetchAnalysisInfoMock).toHaveBeenCalledWith(
        '33936064',
        '/data/Human/Kidney/IgAN/33936064.IgAN.h5ad'
      )
    )
    expect(screen.queryByText(READ_FAILED_RE)).toBeNull()
    expect(await screen.findByRole('button', { name: /study info/i })).toBeTruthy()
  })
})

// The error screen is the failure mode B35 reported: a slow abstract dragged the
// whole /api/analysis-info response past apiFetch's 60s abort, so the user got
// "Failed to load info / Go Back" for a dataset whose stats were available in
// milliseconds. The abstract is now a separate request that cannot blank the page.
const ABORTED_RE = /failed to load info/i

describe('AnalysisPage — the abstract must not be able to blank the page', () => {
  beforeEach(() => {
    findDatasetMock.mockReset().mockResolvedValue(ds() as never)
    fetchAnalysisInfoMock.mockReset().mockResolvedValue({
      pmid: '33936064', abstract: null, abstract_ready: false,
    } as never)
    fetchAbstractMock.mockReset()
    fetchUmapDataMock.mockReset().mockResolvedValue({} as never)
  })

  it('renders the analysis while the abstract is still in flight', async () => {
    // Never settles — stands in for the 4s~125s the real fetch takes.
    fetchAbstractMock.mockReturnValue(new Promise(() => {}))

    render(<AnalysisPage />)

    expect(await screen.findByRole('button', { name: /study info/i })).toBeTruthy()
    expect(screen.queryByText(ABORTED_RE)).toBeNull()
    // 'Go Back' only exists on the error screen; 'Back' in the top bar does not match.
    expect(screen.queryByRole('button', { name: /go back/i })).toBeNull()
  })

  it('keeps the analysis open when the abstract fetch rejects', async () => {
    fetchAbstractMock.mockRejectedValue(new Error('timed out'))

    render(<AnalysisPage />)

    expect(await screen.findByRole('button', { name: /study info/i })).toBeTruthy()
    expect(screen.queryByText(ABORTED_RE)).toBeNull()
  })

  // The two tests above only assert "tab rendered, no error screen" — delete the
  // whole second effect and they still pass. This one pins the feature: the
  // request actually goes out, for the right pmid.
  it('actually asks for the abstract, for the dataset being viewed', async () => {
    fetchAbstractMock.mockResolvedValue({
      pmid: '33936064', abstract: null, abstract_ready: true,
    })

    render(<AnalysisPage />)

    await waitFor(() => expect(fetchAbstractMock).toHaveBeenCalledWith('33936064'))
  })

  // Pins the no-loop property. The effect's deps are primitives derived from
  // `info`, so writing `abstract_ready: false` over `false` is a no-op for
  // Object.is and the effect settles after one extra request. Add `info` (or
  // anything object-valued derived from it) to the dep array and this becomes
  // an infinite loop — nothing else in the suite would catch that.
  it('does not re-request in a loop when the server still reports not-ready', async () => {
    fetchAbstractMock.mockResolvedValue({
      pmid: '33936064', abstract: null, abstract_ready: false,
    })

    render(<AnalysisPage />)

    await screen.findByRole('button', { name: /study info/i })
    await waitFor(() => expect(fetchAbstractMock).toHaveBeenCalled())
    // Let any would-be follow-up effect run before counting.
    await new Promise((r) => setTimeout(r, 50))
    expect(fetchAbstractMock).toHaveBeenCalledTimes(1)
  })

  // The stats request is what the page cannot do without, so it must still be
  // the one that owns the error screen — otherwise the tests above would also
  // pass if the page had stopped reporting failures altogether.
  it('still shows the error screen when the stats request itself fails', async () => {
    fetchAnalysisInfoMock.mockRejectedValue(new Error('boom'))

    render(<AnalysisPage />)

    await screen.findByText(ABORTED_RE)
    expect(screen.queryByRole('button', { name: /study info/i })).toBeNull()
  })
})
