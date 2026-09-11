import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPage from './AnalysisPage'
import { findDataset } from '../api/datasets'
import { fetchAnalysisInfo, fetchUmapData } from '../api/analysis'

vi.mock('react-router-dom', () => ({
  useParams: () => ({ tissue: 'kidney', disease: 'IgAN', pmid: '33936064' }),
  useNavigate: () => vi.fn(),
}))
vi.mock('../api/datasets', () => ({ findDataset: vi.fn() }))
vi.mock('../api/analysis', () => ({
  fetchAnalysisInfo: vi.fn(),
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
