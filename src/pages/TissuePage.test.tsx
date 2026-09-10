import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TissuePage from './TissuePage'
import { fetchDatasets } from '../api/datasets'

// vi.hoisted: the factory below is hoisted above ordinary module scope, so the
// router params have to be reachable from it before anything else runs.
const route = vi.hoisted(() => ({ slug: 'kidney' }))

vi.mock('../api/datasets', () => ({ fetchDatasets: vi.fn() }))
vi.mock('react-router-dom', () => ({
  useParams: () => ({ slug: route.slug }),
  useNavigate: () => vi.fn(),
}))
// The workspace chat pulls in the whole LLM panel; not under test here.
vi.mock('../components/analysis', () => ({ LiteratureTab: () => null }))

const fetchDatasetsMock = vi.mocked(fetchDatasets)

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
  afterEach(() => {
    fetchDatasetsMock.mockReset()
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
    resolveKidney([dataset({ disease: 'IgAN', pmid: '33936064' })])
    await waitFor(() => expect(screen.queryByText('33936064')).toBeNull())
    expect(screen.queryAllByText('IgAN').length).toBe(0)
  })
})
