import { cachedFetch, apiFetch } from './client'
import type { SearchResponse } from './types'

export async function searchDatasets(query: string, signal?: AbortSignal): Promise<SearchResponse> {
  const url = `/api/search?q=${encodeURIComponent(query)}`
  // When signal is provided (for request cancellation), bypass cache
  if (signal) {
    return apiFetch<SearchResponse>(url, { signal })
  }
  return cachedFetch<SearchResponse>(url, 30_000)
}

export async function fetchLog(limit = 50) {
  return cachedFetch(`/api/log?limit=${limit}`)
}
