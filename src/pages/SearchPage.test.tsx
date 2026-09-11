import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import SearchPage from './SearchPage'
import { searchDatasets } from '../api/search'

vi.mock('react-router-dom', () => ({
  useSearchParams: () => [new URLSearchParams('q=IPF')],
  useNavigate: () => vi.fn(),
}))
vi.mock('../api/search', () => ({ searchDatasets: vi.fn() }))
// Header owns its own online-user poll and query box; not under test here.
vi.mock('../components/Header', () => ({ default: () => null }))

const searchDatasetsMock = vi.mocked(searchDatasets)

const hit = (over: Partial<Record<string, unknown>> = {}) => ({
  tissue: 'Lung',
  disease: 'IPF',
  pmid: '32832598',
  search_matches: [['disease', 'IPF']] as [string, string][],
  species: 'Human',
  patient_count: 3,
  sample_count: 6,
  celltype_count: 14,
  group_dist: 'IPF:3, Health:3',
  tissue_obs: 'Lung',
  status: 'ready',
  ...over,
})

/**
 * B30 reaches this page through a different door than the tissue table: the
 * backend's /api/search spreads the whole scanner row into every hit, so an
 * unreadable dataset arrives with `status: 'error'` and three zero counts.
 * Printing those zeros, next to a link that is disabled with no explanation,
 * reads as a legitimately tiny dataset that simply cannot be opened.
 */
describe('SearchPage — an unreadable hit must not render as 0 patients', () => {
  beforeEach(() => {
    searchDatasetsMock.mockReset()
  })

  it('renders an unreadable hit as a failure rather than as 0 patients', async () => {
    searchDatasetsMock.mockResolvedValue({
      query: 'IPF',
      results: [hit({ status: 'error', patient_count: 0, sample_count: 0, celltype_count: 0 })],
    } as never)

    render(<SearchPage />)

    await screen.findByText(/Read failed/i)
    expect(screen.queryByText('0')).toBeNull()
    expect(screen.queryAllByText('—').length).toBeGreaterThanOrEqual(3)
  })

  // Positive control: without this, the assertions above would also pass if the
  // counts column had simply stopped rendering anything at all.
  it('still renders real counts for a readable hit', async () => {
    searchDatasetsMock.mockResolvedValue({ query: 'IPF', results: [hit()] } as never)

    render(<SearchPage />)

    await screen.findByText('32832598')
    expect(screen.queryAllByText('3').length).toBeGreaterThan(0)
    expect(screen.queryByText(/Read failed/i)).toBeNull()
  })
})
