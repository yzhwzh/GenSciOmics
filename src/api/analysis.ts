import { apiFetch, cachedFetch } from './client'
import type {
  AnalysisInfo,
  UmapData,
  ExpressionStats,
  PerSampleTable,
  MutestResult,
  AggregateTable,
  PlotResult,
  UmapRatioPlots,
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

export async function fetchCompositionPlot(realPath: string, gene: string, palette = 'default', gene2 = ''): Promise<PlotResult> {
  const g2 = gene2 ? `&gene2=${encodeURIComponent(gene2)}` : ''
  return apiFetch<PlotResult>(`/api/composition-plot?real_path=${encodeURIComponent(realPath)}&gene=${encodeURIComponent(gene)}&palette=${palette}${g2}`)
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

