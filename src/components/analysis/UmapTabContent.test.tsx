import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import UmapTabContent from './UmapTabContent'

// Mock child components — this file is about the ratio-plot fetch lifecycle,
// not about ECharts / zoom / drag behaviour.
vi.mock('./UmapPlot', () => ({ default: () => <div data-testid="umap-plot">UMAP</div> }))
vi.mock('./ZoomableImage', () => ({
  default: ({ src, alt }: { src: string; alt?: string }) => (
    <img data-testid="zoomable" src={src} alt={alt ?? ''} />
  ),
}))
vi.mock('./DragHandle', () => ({ default: () => <div data-testid="drag-handle">Drag</div> }))
vi.mock('../FilterDropdown', () => ({ default: () => <div data-testid="filter-dropdown" /> }))
vi.mock('react-select/async-creatable', () => ({
  default: () => <div data-testid="gene-select" />,
}))

// The three API calls the component makes. Held in a vi.hoisted block so the
// mock factory below can reference them (vi.mock is hoisted above the imports).
const api = vi.hoisted(() => ({
  fetchUmapRatioPlots: vi.fn(),
  fetchMarkerDotplot: vi.fn(),
  searchGenes: vi.fn(),
}))

vi.mock('../../api/analysis', () => ({
  fetchUmapRatioPlots: api.fetchUmapRatioPlots,
  fetchMarkerDotplot: api.fetchMarkerDotplot,
  searchGenes: api.searchGenes,
}))

/** A promise whose settlement this test controls. */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const baseProps = {
  realPath: '/data/some/Data/Human/Lung/COPD/a.h5ad',
  umapData: null,
  umapLoading: false,
  colorBy: 'Group',
  onColorByChange: vi.fn(),
  geneName: '',
  onGeneNameChange: vi.fn(),
  geneName2: '',
  onGeneName2Change: vi.fn(),
  palette: 'default',
  onPaletteChange: vi.fn(),
}

/** The spinner the component renders while a ratio plot is in flight. */
const spinners = () => document.querySelectorAll('.animate-spin')
const noData = () => screen.queryAllByText('No data')

// "No data" appears in four places in this component: the three ratio panels
// (:226 stacked_bar, :236 count bar, :261 boxplot) and the marker dotplot at
// :367. Only the first three share the `loading` flag under test, so the
// dotplot's copy must be silenced before any count below means anything —
// `beforeEach` feeds it an image, and `expectDotplotSilent()` proves it worked.
// Without that, test 2 would pass even if the ratio panels never said "No data"
// at all, because :367 would still be there to satisfy the count.
const expectDotplotSilent = () =>
  expect(screen.getByAltText('Marker dotplot')).toBeInTheDocument()

/** Let queued microtasks (the dotplot request) settle inside act(). */
const flush = () => act(async () => { await Promise.resolve() })

describe('UmapTabContent — ratio plot fetch lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // The dotplot request runs alongside the ratio request in every test.
    // Resolve it immediately, with an image, so it contributes neither a
    // spinner nor a "No data" of its own (see expectDotplotSilent above).
    api.fetchMarkerDotplot.mockResolvedValue({ image: 'DOTPLOT' })
    api.searchGenes.mockResolvedValue([])
  })

  // Regression: `setLoading(true)` did not exist in this component, so `loading`
  // was false for the whole request. The panel therefore rendered the "No data"
  // branch — the one reserved for an empty result — while the request was still
  // in flight, and only the Loader at :221 was unreachable. This test fails
  // before the fix.
  it('does not claim "No data" while the request is still pending', async () => {
    const pending = deferred<never>()
    api.fetchUmapRatioPlots.mockReturnValue(pending.promise)

    render(<UmapTabContent {...baseProps} />)
    await flush()

    expectDotplotSilent()
    // Before the fix this was 3: the two visible ratio panels plus the dotplot,
    // which had not settled yet at the moment of the old assertion.
    expect(noData()).toHaveLength(0)
    expect(spinners().length).toBeGreaterThan(0)
  })

  // Guard against "fixing" the above by simply never rendering "No data":
  // an empty result must still say so, or a genuinely empty dataset would sit
  // under a spinner forever.
  it('still shows "No data" once a request settles empty', async () => {
    api.fetchUmapRatioPlots.mockResolvedValue({})

    render(<UmapTabContent {...baseProps} />)

    // Exactly the two visible ratio panels (:226 and :261 — the third lives on
    // the "Cells per Sample" tab, which is not mounted). Asserting the count
    // rather than "> 0" is what makes this an isolation check: a stray "No data"
    // from anywhere else would break it.
    await waitFor(() => expect(noData()).toHaveLength(2))
    expectDotplotSilent()
    expect(spinners()).toHaveLength(0)
  })

  it('renders the plot and clears the spinner once the request settles', async () => {
    api.fetchUmapRatioPlots.mockResolvedValue({ stacked_bar: 'AAAA', ratio_boxplot: 'BBBB' })

    render(<UmapTabContent {...baseProps} />)

    expect(await screen.findByAltText('Cell ratio per sample')).toBeInTheDocument()
    expectDotplotSilent()
    expect(spinners()).toHaveLength(0)
    expect(noData()).toHaveLength(0)
  })

  it('shows the error instead of "No data" when the request fails', async () => {
    api.fetchUmapRatioPlots.mockRejectedValue(new Error('backend exploded'))

    render(<UmapTabContent {...baseProps} />)

    // The single `error` state is rendered twice — in the tab panel (:222) and
    // above the boxplot (:259) — so this is an AllBy query, not a By one.
    expect(await screen.findAllByText('backend exploded')).toHaveLength(2)
    expectDotplotSilent()
    expect(noData()).toHaveLength(0)
  })

  // Switching palette changes the effect's dependency array. Without on-entry
  // clearing, the previous palette's plot stayed on screen and a previous
  // error stayed under it while the new request ran.
  it('clears the previous plot when the palette changes', async () => {
    api.fetchUmapRatioPlots.mockResolvedValueOnce({ stacked_bar: 'OLD' })
    const { rerender } = render(<UmapTabContent {...baseProps} />)
    expect(await screen.findByAltText('Cell ratio per sample')).toBeInTheDocument()

    const pending = deferred<never>()
    api.fetchUmapRatioPlots.mockReturnValueOnce(pending.promise)
    rerender(<UmapTabContent {...baseProps} palette="nature" />)
    await flush()

    expect(screen.queryByAltText('Cell ratio per sample')).toBeNull()
    expectDotplotSilent()
    expect(noData()).toHaveLength(0)
    expect(spinners().length).toBeGreaterThan(0)
    expect(api.fetchUmapRatioPlots).toHaveBeenLastCalledWith(baseProps.realPath, 'Group', 'nature')
  })

  // A failed request must not leave its message on screen for the next one.
  it('clears a previous error when the palette changes', async () => {
    api.fetchUmapRatioPlots.mockRejectedValueOnce(new Error('stale failure'))
    const { rerender } = render(<UmapTabContent {...baseProps} />)
    expect(await screen.findAllByText('stale failure')).toHaveLength(2)

    const pending = deferred<never>()
    api.fetchUmapRatioPlots.mockReturnValueOnce(pending.promise)
    rerender(<UmapTabContent {...baseProps} palette="bold" />)
    await flush()

    expect(screen.queryAllByText('stale failure')).toHaveLength(0)
  })

  // Found while fixing the above: the dotplot effect at :109-121 carried the
  // identical missing-setter defect. Every other test here deliberately keeps
  // the dotplot silent to isolate the ratio panels, so this is the only place
  // that exercises :362's Loader and :367's "No data".
  it('does not claim "No data" in the dotplot panel while its request is pending', async () => {
    api.fetchUmapRatioPlots.mockResolvedValue({})
    const pending = deferred<never>()
    api.fetchMarkerDotplot.mockReturnValue(pending.promise)

    render(<UmapTabContent {...baseProps} />)

    // The two ratio panels have settled empty and do say "No data"; a third
    // one can only be the dotplot's :367.
    await waitFor(() => expect(noData()).toHaveLength(2))
    expect(screen.queryByAltText('Marker dotplot')).toBeNull()
    expect(spinners()).toHaveLength(1)
  })
})
