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

export interface DatasetSummary {
  organs: number
  diseases: number
  studies: number
  omics: number
}

/**
 * 首页 Hero 区四个数字的唯一来源。每个都是**去重计数**，一条记录只落进一个桶：
 *
 *  - organs   去重 `tissue`（忽略大小写 —— scanner 给出的标签大小写不统一）
 *  - diseases 去重 `disease`，**排除 `Health`**：Health 是分组不是病种，算进去会让
 *             标着 Diseases 的一栏里出现一个叫「健康」的条目
 *  - studies  去重 `pmid`，**按套数不按文件数**：Tabula Sapiens 一篇（PMID 35549404）
 *             被拆成 29 个单器官文件，按文件数会数成 29 套。统计表 /api/stats 同样
 *             按 PMID 计套数，两边口径必须一致
 *  - omics    去重 `omics_type`，从数据实算（原先是写死的 4，实际只有 3 类）
 *
 * 这三条错法都不会报错，只会让数字悄悄偏，所以口径钉在 datasets.test.ts 里。
 */
export function summarizeDatasets(datasets: DatasetInfo[]): DatasetSummary {
  const organs = new Set<string>()
  const diseases = new Set<string>()
  const studies = new Set<string>()
  const omics = new Set<string>()

  for (const d of datasets) {
    if (d.tissue) organs.add(d.tissue.toLowerCase())
    if (d.disease && d.disease.toLowerCase() !== 'health') diseases.add(d.disease)
    if (d.pmid) studies.add(d.pmid)
    if (d.omics_type) omics.add(d.omics_type)
  }

  return { organs: organs.size, diseases: diseases.size, studies: studies.size, omics: omics.size }
}
