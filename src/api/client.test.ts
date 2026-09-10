import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cachedFetch, clearCache, CACHE_TTL } from './client'

/**
 * The backend serves every list endpoint as `[]` until its initial filesystem
 * scan finishes. Caching that empty answer for the full five-minute TTL means a
 * tissue page opened in that window pins "no data" long after the scan that
 * would have disproved it — so an empty list must never be cached. These tests
 * pin that rule, since losing it is invisible until it presents as a bug report
 * about missing data.
 */
describe('cachedFetch — empty lists are never cached', () => {
  const jsonResponse = (data: unknown) => ({ ok: true, json: async () => data }) as Response

  beforeEach(() => {
    clearCache()
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    clearCache()
  })

  it('refetches after an empty list instead of serving the cached empty result', async () => {
    // First call: the scan has not finished yet. Second: it has.
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([{ pmid: '33936064' }]))

    expect(await cachedFetch('/api/datasets?tissue=kidney')).toEqual([])
    expect(await cachedFetch('/api/datasets?tissue=kidney')).toEqual([{ pmid: '33936064' }])
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('serves a non-empty list from cache without a second request', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue(jsonResponse([{ pmid: '33936064' }]))

    const first = await cachedFetch('/api/datasets?tissue=kidney')
    const second = await cachedFetch('/api/datasets?tissue=kidney')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    // Same reference is the point: callers rely on React bailing out of a
    // re-render when nothing changed.
    expect(second).toBe(first)
  })

  it('still caches an object response — the default rule only recognises arrays', async () => {
    // {} is not a list, so the empty-array exemption does not apply. Pinning
    // this keeps the default from silently widening into "never cache anything
    // falsy", which would disable caching for every plot and table payload.
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue(jsonResponse({}))

    await cachedFetch('/api/some-object')
    await cachedFetch('/api/some-object')

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('lets a caller refuse to cache an object that reports its own emptiness', async () => {
    // /api/stats is the real case: {tissues: [], species: []} before the first
    // scan finishes is indistinguishable from a healthy empty atlas, and the
    // default rule cannot see inside the object to tell them apart.
    const fetchMock = vi.mocked(fetch)
    const isEmpty = (s: { tissues: string[]; species: string[] }) =>
      s.tissues.length === 0 && s.species.length === 0

    fetchMock
      .mockResolvedValueOnce(jsonResponse({ tissues: [], species: [] }))
      .mockResolvedValueOnce(jsonResponse({ tissues: ['Lung'], species: ['Human'] }))

    const first = await cachedFetch('/api/stats', CACHE_TTL, isEmpty)
    expect(first).toEqual({ tissues: [], species: [] })

    const second = await cachedFetch('/api/stats', CACHE_TTL, isEmpty)
    expect(second).toEqual({ tissues: ['Lung'], species: ['Human'] })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    // A populated atlas is a real answer and is cached from then on.
    await cachedFetch('/api/stats', CACHE_TTL, isEmpty)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('surfaces the HTTP error rather than caching a fallback', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue({ ok: false, status: 502, json: async () => ({}) } as Response)

    await expect(cachedFetch('/api/datasets?tissue=kidney')).rejects.toThrow('HTTP 502')
  })
})
