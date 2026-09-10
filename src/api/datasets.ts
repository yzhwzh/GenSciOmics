import { cachedFetch, apiFetch, CACHE_TTL } from './client'
import type { DatasetInfo, StatsResponse } from './types'

export async function fetchDatasets(tissue?: string): Promise<DatasetInfo[]> {
  const url = tissue ? `/api/datasets?tissue=${encodeURIComponent(tissue)}` : '/api/datasets'
  return cachedFetch<DatasetInfo[]>(url)
}

// Bypasses the 5-minute response cache. For callers that poll a list the
// backend is actively rewriting — going through cachedFetch there returns the
// same array reference on every tick, which React bails out of re-rendering,
// so the poll silently does nothing until the TTL expires.
export async function fetchDatasetsFresh(tissue?: string): Promise<DatasetInfo[]> {
  const q = tissue ? `?tissue=${encodeURIComponent(tissue)}&t=${Date.now()}` : `?t=${Date.now()}`
  return apiFetch<DatasetInfo[]>(`/api/datasets${q}`)
}

export async function fetchTissues(): Promise<string[]> {
  return cachedFetch<string[]>('/api/tissues')
}

// /api/stats reports its emptiness inside an object rather than as a bare [],
// so the default empty-array rule cannot see it. Before the first scan finishes
// it answers with no tissues and no species, and caching that would leave the
// cross-tabulation blank for the full TTL — the same trap the list endpoints
// have (B29), just wearing a different shape.
export async function fetchStats(): Promise<StatsResponse> {
  return cachedFetch<StatsResponse>(
    '/api/stats',
    CACHE_TTL,
    // Array.isArray, not just .length: apiFetch casts res.json() without
    // validating it, so a 200 with an unexpected body would throw a TypeError
    // from inside cachedFetch rather than degrade.
    (s) => Array.isArray(s?.tissues) && Array.isArray(s?.species)
      && s.tissues.length === 0 && s.species.length === 0,
  )
}

export async function findDataset(tissue: string, disease: string, pmid: string, omicsType?: string): Promise<DatasetInfo | null> {
  // Bypass cache — scanner may have updated dataset list since last fetch
  const datasets = await apiFetch<DatasetInfo[]>(`/api/datasets?t=${Date.now()}`)
  return datasets.find(
    (d) =>
      d.tissue.toLowerCase() === tissue.toLowerCase() &&
      d.disease.toLowerCase() === disease.toLowerCase() &&
      d.pmid === pmid &&
      (!omicsType || d.omics_type === omicsType)
  ) ?? null
}

// Lightweight lookup endpoint instead of fetching all datasets
export async function lookupDataset(tissue: string, disease: string, pmid: string): Promise<DatasetInfo | null> {
  return findDataset(tissue, disease, pmid)
}
