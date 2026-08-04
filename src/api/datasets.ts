import { cachedFetch, apiFetch } from './client'
import type { DatasetInfo, StatsResponse } from './types'

export async function fetchDatasets(tissue?: string): Promise<DatasetInfo[]> {
  const url = tissue ? `/api/datasets?tissue=${encodeURIComponent(tissue)}` : '/api/datasets'
  return cachedFetch<DatasetInfo[]>(url)
}

export async function fetchTissues(): Promise<string[]> {
  return cachedFetch<string[]>('/api/tissues')
}

export async function fetchStats(): Promise<StatsResponse> {
  return cachedFetch<StatsResponse>('/api/stats')
}

export async function findDataset(tissue: string, disease: string, pmid: string): Promise<DatasetInfo | null> {
  // Bypass cache — scanner may have updated dataset list since last fetch
  const datasets = await apiFetch<DatasetInfo[]>(`/api/datasets?t=${Date.now()}`)
  return datasets.find(
    (d) =>
      d.tissue.toLowerCase() === tissue.toLowerCase() &&
      d.disease.toLowerCase() === disease.toLowerCase() &&
      d.pmid === pmid
  ) ?? null
}

// Lightweight lookup endpoint instead of fetching all datasets
export async function lookupDataset(tissue: string, disease: string, pmid: string): Promise<DatasetInfo | null> {
  return findDataset(tissue, disease, pmid)
}
