import { apiFetch, cachedFetch } from './client'
import type {
  AnalysisInfo,
  UmapData,
  ExpressionStats,
  PerSampleTable,
  MutestResult,
  AggregateTable,
  PlotResult,
  MarkerDotplotResult,
  UmapRatioPlots,
  BulkDeResult,
  BulkDiseasesResult,
  BulkGroupsResult,
  BulkVolcanoResult,
  SkillDef,
  ChatMessage,
  LLMConfig,
  ChatResponse,
} from './types'

// ─── Vite HMR reload protection during active SSE streams ──────
// Vite's HMR client calls window.location.reload() on full-reload
// events. We block it via beforeunload when SSE streams are active.
// window.location.reload is read-only in strict mode (ES modules),
// so we use the beforeunload event instead.
let _sseActiveCount = 0
window.addEventListener('beforeunload', (e) => {
  if (_sseActiveCount > 0) {
    e.preventDefault()
    // no returnValue = silent cancel, no dialog shown
  }
})

export function _enterSSE() { _sseActiveCount++ }
export function _leaveSSE() { _sseActiveCount = Math.max(0, _sseActiveCount - 1) }

// ─── Per-user identity ──────────────────────────────────────────
// 浏览器级稳定 user_id（localStorage 持久化）：每台浏览器/设备 = 一个用户。
// 后端据此隔离 agent 记忆到 server/memory/<user_id>/。
// 与 OnlineUsers 心跳的临时 randomUUID 无关（后者只用于在线计数去重）。
const USER_KEY = 'gensci_user_id'
let _cachedUserId: string | null = null
function getClientUserId(): string {
  if (_cachedUserId) return _cachedUserId
  try {
    const existing = localStorage.getItem(USER_KEY)
    if (existing) { _cachedUserId = existing; return existing }
  } catch { /* localStorage unavailable — fall through to in-memory id */ }
  const id = crypto.randomUUID?.() ?? `u-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  try { localStorage.setItem(USER_KEY, id) } catch { /* ignore */ }
  _cachedUserId = id
  return id
}

export async function fetchAnalysisInfo(pmid: string, realPath: string): Promise<AnalysisInfo> {
  return apiFetch<AnalysisInfo>(`/api/analysis-info?pmid=${pmid}&real_path=${encodeURIComponent(realPath)}`)
}

export async function fetchUmapData(
  realPath: string,
  colorBy: string,
  maxPoints = 50000,
  gene?: string,
  palette = 'default',
  gene2?: string,
): Promise<UmapData> {
  let url = `/api/umap-data?real_path=${encodeURIComponent(realPath)}&color_by=${colorBy}&max_points=${maxPoints}&palette=${palette}`
  if (colorBy === 'Gene' && gene?.trim()) {
    url += `&gene=${encodeURIComponent(gene.trim())}`
  }
  if (colorBy === 'Gene' && gene2?.trim()) {
    url += `&gene2=${encodeURIComponent(gene2.trim())}`
  }
  return cachedFetch<UmapData>(url)
}

export async function searchGenes(realPath: string, query: string): Promise<string[]> {
  const data = await apiFetch<{ genes: string[] }>(
    `/api/search-genes?real_path=${encodeURIComponent(realPath)}&q=${encodeURIComponent(query)}`
  )
  return Array.isArray(data.genes) ? data.genes : []
}

export async function fetchExpressionStats(
  realPath: string,
  genes: string,
  groupBy = 'sample',
  cellType?: string,
  conditionCol?: string
): Promise<ExpressionStats> {
  const params = new URLSearchParams({ real_path: realPath, genes, group_by: groupBy })
  if (cellType) params.set('cell_type', cellType)
  if (conditionCol) params.set('condition_col', conditionCol)
  return apiFetch<ExpressionStats>(`/api/expression-stats?${params}`)
}

export async function fetchPerSampleTable(
  realPath: string,
  genes: string,
  groupCol = 'Group',
  celltypeCol = 'CellType'
): Promise<PerSampleTable> {
  const params = new URLSearchParams({
    real_path: realPath,
    genes,
    group_col: groupCol,
    celltype_col: celltypeCol,
  })
  return apiFetch<PerSampleTable>(`/api/per-sample-table?${params}`)
}

export async function fetchPerSampleMutest(
  realPath: string,
  genes: string,
  groupCol = 'Group',
  celltypeCol = 'CellType',
  minCells = 10
): Promise<MutestResult> {
  const params = new URLSearchParams({
    real_path: realPath,
    genes,
    group_col: groupCol,
    celltype_col: celltypeCol,
    min_cells: String(minCells),
  })
  return apiFetch<MutestResult>(`/api/per-sample-mutest?${params}`)
}

export async function fetchAggregateTable(
  realPath: string,
  genes: string,
  groupCol = 'Group',
  celltypeCol = 'CellType'
): Promise<AggregateTable> {
  const params = new URLSearchParams({
    real_path: realPath,
    genes,
    group_col: groupCol,
    celltype_col: celltypeCol,
  })
  return apiFetch<AggregateTable>(`/api/aggregate-table?${params}`)
}

export async function fetchPlot(
  realPath: string,
  gene: string,
  conditionCol: string,
  metric: string,
  plotType: 'boxplot' | 'barplot',
  minCells?: number,
  palette = 'default'
): Promise<PlotResult> {
  const params = new URLSearchParams({
    real_path: realPath,
    gene,
    condition_col: conditionCol,
    metric,
    plot_type: plotType,
    palette,
  })
  if (minCells !== undefined) params.set('min_cells', String(minCells))
  return cachedFetch<PlotResult>(`/api/plot?${params}`)
}

// ─── v3: LLM Chat ──────────────────────────────────────────────

export async function fetchSkills(): Promise<SkillDef[]> {
  return apiFetch<SkillDef[]>('/api/skills')
}

export async function sendChatMessage(
  messages: ChatMessage[],
  realPath: string,
  config: LLMConfig,
): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/api/llm/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages,
      real_path: realPath,
      api_key: config.apiKey,
      model: config.model,
      base_url: config.baseUrl,
      temperature: config.temperature,
      user_id: getClientUserId(),
    }),
  })
}

// SSE goes through Vite proxy; HMR isolated on port 5174 to prevent disconnect

export async function sendChatMessageStreaming(
  messages: ChatMessage[],
  realPath: string,
  config: LLMConfig,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
  omicsType?: string,
): Promise<void> {
  _enterSSE()
  try {
    const response = await fetch('/api/llm/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        messages,
        real_path: realPath,
        api_key: config.apiKey,
        model: config.model,
        base_url: config.baseUrl,
        temperature: config.temperature,
        omics_type: omicsType,
        user_id: getClientUserId(),
      }),
    })

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.error || `HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No response body')

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''

      for (const block of lines) {
        const eventMatch = block.match(/^event: (.+)$/m)
        const dataMatch = block.match(/^data: (.+)$/m)
        if (eventMatch && dataMatch) {
          try {
            const data = JSON.parse(dataMatch[1])
            onEvent(eventMatch[1], data)
          } catch {
            // skip parse errors
          }
        }
      }
    }
  } finally {
    _leaveSSE()
  }
}

export async function sendLiteratureMessageStreaming(
  messages: ChatMessage[],
  config: LLMConfig,
  context: string,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  _enterSSE()
  try {
    const response = await fetch('/api/llm/literature/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        messages,
        api_key: config.apiKey,
        model: config.model,
        base_url: config.baseUrl,
        temperature: config.temperature,
        context,
        user_id: getClientUserId(),
      }),
    })

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.error || `HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No response body')

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''

      for (const block of lines) {
        const eventMatch = block.match(/^event: (.+)$/m)
        const dataMatch = block.match(/^data: (.+)$/m)
        if (eventMatch && dataMatch) {
          try {
            const data = JSON.parse(dataMatch[1])
            onEvent(eventMatch[1], data)
          } catch {
            // skip parse errors
          }
        }
      }
    }
  } finally {
    _leaveSSE()
  }
}

export async function fetchCompositionPlot(realPath: string, gene: string, palette = 'default', gene2 = '', gene2Label = '', gene2Op = ''): Promise<PlotResult> {
  const g2 = gene2 ? `&gene2=${encodeURIComponent(gene2)}` : ''
  const lbl = gene2Label?.trim() ? `&gene2_label=${encodeURIComponent(gene2Label.trim())}` : ''
  // Only send the non-default op, mirroring gene2/gene2_label: omitting it keeps
  // the URL byte-identical to before this feature, so caches and old clients agree.
  const op = gene2Op === 'and' && gene2 ? '&gene2_op=and' : ''
  return apiFetch<PlotResult>(`/api/composition-plot?real_path=${encodeURIComponent(realPath)}&gene=${encodeURIComponent(gene)}&palette=${palette}${g2}${lbl}${op}`)
}

export async function fetchUmapRatioPlots(
  realPath: string,
  groupVar = 'Group',
  palette = 'default'
): Promise<UmapRatioPlots> {
  const params = new URLSearchParams({ real_path: realPath, group_var: groupVar, palette })
  return cachedFetch<UmapRatioPlots>(`/api/umap-ratio-plots?${params}`)
}

export async function fetchCellTypes(realPath: string): Promise<string[]> {
  const data = await apiFetch<{ cell_types: string[] }>(
    `/api/cell-types?real_path=${encodeURIComponent(realPath)}`
  )
  return Array.isArray(data.cell_types) ? data.cell_types : []
}

export async function fetchRawExpression(
  realPath: string,
  genes: string,
  cellTypes: string,
): Promise<Blob> {
  const response = await fetch('/api/raw-expression', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ real_path: realPath, genes, cell_types: cellTypes }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.error || `HTTP ${response.status}`)
  }
  return response.blob()
}

export async function fetchMarkerDotplot(
  realPath: string,
  palette = 'default',
  groupFilter = '',
  genes = '',
): Promise<MarkerDotplotResult> {
  const params = new URLSearchParams({
    real_path: realPath,
    palette,
  })
  if (groupFilter) params.set('group_filter', groupFilter)
  if (genes) params.set('genes', genes)
  return apiFetch<MarkerDotplotResult>(`/api/marker-dotplot?${params}`)
}

// ─── Bulk RNA analysis ────────────────────────────────────────

export async function fetchBulkBoxplot(
  realPath: string,
  gene: string,
  disease?: string,
  palette = 'default',
  targetGroup?: string,
  groups?: string[],
  xFactorCol?: string
): Promise<PlotResult> {
  const params = new URLSearchParams({ real_path: realPath, gene, palette })
  if (disease) params.set('disease', disease)
  if (targetGroup && targetGroup !== 'All') params.set('target_group', targetGroup)
  if (groups && groups.length > 0) params.set('groups', groups.join(','))
  // xFactorCol: panel x-axis obs column ('Disease' = default → not sent).
  if (xFactorCol) params.set('x_factor', xFactorCol)
  return cachedFetch<PlotResult>(`/api/bulk-boxplot?${params}`)
}

export interface BulkAxes {
  diseases: string[]
  tissueColumn: string | null
}

/** Diseases + optional organ/tissue panel column for a bulk/protein dataset. */
export async function fetchBulkAxes(realPath: string): Promise<BulkAxes> {
  const data = await apiFetch<BulkDiseasesResult>(
    `/api/bulk-diseases?real_path=${encodeURIComponent(realPath)}`
  )
  return {
    diseases: Array.isArray(data.diseases) ? data.diseases : [],
    tissueColumn: data.tissue_column ?? null
  }
}

export async function fetchBulkDe(
  realPath: string,
  disease?: string,
  topN = 100,
  caseGroup?: string,
  controlGroup?: string
): Promise<BulkDeResult> {
  const params = new URLSearchParams({ real_path: realPath, top_n: String(topN) })
  if (disease) params.set('disease', disease)
  if (caseGroup) params.set('case_group', caseGroup)
  if (controlGroup) params.set('control_group', controlGroup)
  return apiFetch<BulkDeResult>(`/api/bulk-de?${params}`)
}

export async function fetchBulkGroups(realPath: string): Promise<string[]> {
  const data = await apiFetch<BulkGroupsResult>(
    `/api/bulk-groups?real_path=${encodeURIComponent(realPath)}`
  )
  return Array.isArray(data.groups) ? data.groups : []
}

export async function fetchBulkVolcano(
  realPath: string,
  disease?: string,
  fcThresh = 1.0,
  alpha = 0.05,
  caseGroup?: string,
  controlGroup?: string
): Promise<BulkVolcanoResult> {
  const params = new URLSearchParams({ real_path: realPath, fc: String(fcThresh), alpha: String(alpha) })
  if (disease) params.set('disease', disease)
  if (caseGroup) params.set('case_group', caseGroup)
  if (controlGroup) params.set('control_group', controlGroup)
  // server caches the image; longer timeout for the cold full-matrix t-test
  return apiFetch<BulkVolcanoResult>(`/api/bulk-volcano?${params}`, undefined, 120_000)
}

