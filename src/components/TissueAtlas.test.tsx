import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TissueAtlas from './TissueAtlas'
import { fetchDatasets } from '../api/datasets'

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../api/datasets', () => ({ fetchDatasets: vi.fn() }))

const fetchDatasetsMock = vi.mocked(fetchDatasets)

const ds = (over: Partial<Record<string, unknown>> = {}) => ({
  species: 'Human',
  tissue: 'Kidney',
  disease: 'IgAN',
  pmid: '1',
  omics_type: 'scRNA',
  status: 'ready',
  ...over,
})

/**
 * The species tabs swap the body outline but reused one dataset map built from
 * every species at once. Mouse and Monkey organs use the same slugs as the
 * Human tissue names (kidney/lung/liver/colon…), so lowercasing collapsed them
 * onto one key and the non-Human tabs displayed Human counts — 93 of the 96
 * live datasets are Human, so those tabs were almost entirely Human numbers.
 */
describe('TissueAtlas — counts must not cross species', () => {
  beforeEach(() => {
    fetchDatasetsMock.mockReset()
  })

  const hoverOrgan = async (label: string | RegExp) => {
    fireEvent.mouseEnter(await screen.findByRole('button', { name: label }))
  }

  it('shows only the active species when organ slugs collide', async () => {
    fetchDatasetsMock.mockResolvedValue([
      ds({ species: 'Human', tissue: 'Kidney', disease: 'IgAN' }),
      ds({ species: 'Mouse', tissue: 'Kidney', disease: 'UUO' }),
    ] as never)

    render(<TissueAtlas />)

    // Human tab first — the Mouse dataset must not appear here either.
    await hoverOrgan(/Kidney/i)
    await screen.findByText('IgAN')
    expect(screen.queryByText('UUO')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Mouse' }))
    await hoverOrgan(/Kidney/i)

    await screen.findByText('UUO')
    expect(screen.queryByText('IgAN')).toBeNull()
  })

  it('reports "No datasets yet" for a species that has none in that organ', async () => {
    fetchDatasetsMock.mockResolvedValue([
      ds({ species: 'Human', tissue: 'Kidney', disease: 'IgAN' }),
    ] as never)

    render(<TissueAtlas />)
    await userEvent.click(screen.getByRole('button', { name: 'Monkey' }))
    await hoverOrgan(/Kidney/i)

    await screen.findByText(/No datasets yet/i)
    expect(screen.queryByText('IgAN')).toBeNull()
  })
})
