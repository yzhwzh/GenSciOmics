export interface DatasetInfo {
  species?: string
  tissue: string
  disease: string
  pmid: string
  real_path: string
  filename?: string
  size_mb?: number
  status?: string
  omics_type?: string
  patient_count?: number
  sample_count?: number
  celltype_count?: number
  n_obs?: number
  n_vars?: number
  disease_count?: number
  group_dist?: string
  tissue_obs?: string
  data_type?: string
  annotation_source?: string
  marker_major?: Record<string, string[]> | null
}

export interface TissueStat {
  total_datasets: number
  diseases: { name: string; count: number }[]
}

export interface StatsResponse {
  species: string[]
  tissues: string[]
  rows: Record<string, Record<string, TissueStat>>
  species_dataset_counts?: Record<string, number>
  species_health_counts?: Record<string, number>
  species_disease_counts?: Record<string, number>
}

export interface AbstractInfo {
  title: string
  abstract: string
  journal: string
  authors: string
  year: string
  doi: string
  methods?: string
  results?: string
}

export interface AnalysisStats {
  cells: number
  genes: number
  patient_count: number
  sample_count: number
  celltype_count: number
  cell_type_names: string[]
  disease_count?: number
  group_names?: string[]
  group_dist?: string
}

export interface AnalysisInfo {
  pmid: string
  abstract: AbstractInfo
  stats: AnalysisStats
}

export interface BulkDeRow {
  gene: string
  mean_tumor: number | null
  mean_normal: number | null
  log2fc: number | null
  pvalue: number | null
  padj: number | null
}

export interface BulkDeResult {
  genes?: BulkDeRow[]
  n_total?: number
  n_tumor?: number
  n_normal?: number
  disease?: string
  error?: string
}

export interface BulkDiseasesResult {
  diseases: string[]
  error?: string
}

export interface BulkVolcanoResult {
  image?: string
  error?: string
  width?: number
  height?: number
  n_up?: number
  n_down?: number
  n_ns?: number
}

export interface UmapLegendItem {
  name: string
  color?: string
  count?: number
  min?: number
  max?: number
}

export interface UmapData {
  points: [number, number][]
  colors: string[]
  legend: UmapLegendItem[]
  color_type: 'categorical' | 'continuous' | 'dual_gene'
  n_cells: number
  sampled: boolean
  sample_step: number
}

export interface ExpressionRow {
  gene: string
  sample?: string
  cell_type?: string
  condition?: string
  mean_expression: number
  expression_pct: number
  n_cells: number
  n_expressing: number
}

export interface ExpressionStats {
  genes: string[]
  conditions: string[]
  samples: string[]
  cell_types: string[]
  by_sample: ExpressionRow[]
  by_celltype: ExpressionRow[]
  by_sample_celltype: ExpressionRow[]
}

export interface PerSampleRow {
  SampleID: string
  CellType: string
  CellTypeNumber: number
  CellTotalNumber: number
  CellTypeRatio: number
  Gene: string
  GeneMeanExpression: number
  GeneExpressionPct: number
  GeneExpressionNumber: number
  Group: string
}

export interface PerSampleTable {
  rows: PerSampleRow[]
  n_rows: number
}

export interface MutestResult {
  groups: string[]
  cell_types: string[]
  pairs: string[]
  mean_matrix: (number | null)[][]
  pct_matrix: (number | null)[][]
}

export interface AggregateRow {
  Gene: string
  CellType: string
  Group: string
  CellTypeNumber: number
  CellTotalNumber: number
  CellTypeRatio: number
  GeneMeanExpression: number
  GeneExpressionPct: number
  GeneExpressionNumber: number
}

export interface FisherResult {
  pairs: string[]
  cell_types: string[]
  matrix: (number | null)[][]
}

export interface AggregateTable {
  rows: AggregateRow[]
  n_rows: number
  groups: string[]
  fisher: FisherResult
}

export interface PlotResult {
  image?: string
  error?: string
  width?: number
  height?: number
}

export interface MarkerDotplotResult {
  image?: string
  error?: string
  width?: number
  height?: number
  groups?: string[]
}

export interface CellRatioPlot {
  stacked_bar: string
  boxplot: string
  n_cell_types?: number
  n_samples?: number
}

export interface UmapRatioPlots {
  stacked_bar: string
  cell_count_bar: string
  ratio_boxplot: string
  pairwise?: MutestResult
  n_cell_types?: number
  n_samples?: number
  low_cell_pct?: number
}

export interface SearchMatch {
  tissue: string
  disease: string
  pmid: string
  search_matches: [string, string][]
  species?: string
  patient_count?: number
  sample_count?: number
  celltype_count?: number
  group_dist?: string
  tissue_obs?: string
  status?: string
}

export interface SearchResponse {
  query: string
  results: SearchMatch[]
}

export interface LogEntry {
  time: string
  type: string
  message: string
  detail: string
}

export const PALETTE_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'pastel', label: 'Pastel' },
  { value: 'bold', label: 'Bold' },
  { value: 'nature', label: 'Nature' },
  { value: 'tab10', label: 'Tab10' },
] as const

export type PaletteName = (typeof PALETTE_OPTIONS)[number]['value']

// ─── v3: LLM Chat Types ──────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  tool_calls?: ToolCall[]
  tool_call_id?: string
  tool_results?: ToolResult[]
}

export interface ToolCall {
  id: string
  type: 'function'
  function: {
    name: string
    arguments: string
  }
}

export interface SkillParam {
  name: string
  type: string
  description: string
  required?: boolean
  enum?: string[]
}

export interface SkillDef {
  name: string
  description: string
  has_tool?: boolean
  has_skill_md?: boolean
  parameters?: {
    type: string
    properties: Record<string, unknown>
    required: string[]
  } | null
}

export interface ToolResult {
  name: string
  args?: Record<string, unknown>
  result?: unknown
  error?: string | null
}

export interface LLMConfig {
  model: string
  apiKey: string
  baseUrl: string
  temperature: number
}

export interface ChatResponse {
  content?: string
  error?: string
  tool_results?: ToolResult[]
  iterations?: number
}

export interface SSEMessage {
  content?: string
}

export interface SSEToolCall {
  name: string
  args?: string
}

export interface SSEToolResult {
  name: string
  result?: unknown
  error?: string | null
}

export const LLM_MODELS = [
  // DeepSeek
  { value: 'deepseek-chat', label: 'DeepSeek V3', group: 'DeepSeek' },
  { value: 'deepseek-reasoner', label: 'DeepSeek R1', group: 'DeepSeek' },
  // OpenAI
  { value: 'gpt-4o', label: 'GPT-4o', group: 'OpenAI' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini', group: 'OpenAI' },
  { value: 'gpt-4.1', label: 'GPT-4.1', group: 'OpenAI' },
  { value: 'gpt-4.1-mini', label: 'GPT-4.1 Mini', group: 'OpenAI' },
  { value: 'gpt-4.1-nano', label: 'GPT-4.1 Nano', group: 'OpenAI' },
  { value: 'o3', label: 'o3', group: 'OpenAI' },
  { value: 'o4-mini', label: 'o4-mini', group: 'OpenAI' },
  // Claude (Anthropic)
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', group: 'Anthropic' },
  { value: 'claude-opus-4-8', label: 'Claude Opus 4.8', group: 'Anthropic' },
  { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5', group: 'Anthropic' },
  // Qwen (Alibaba)
  { value: 'qwen-plus', label: 'Qwen Plus', group: 'Qwen' },
  { value: 'qwen-max', label: 'Qwen Max', group: 'Qwen' },
  { value: 'qwen-turbo', label: 'Qwen Turbo', group: 'Qwen' },
  { value: 'qwen3-235b-a22b', label: 'Qwen3 235B', group: 'Qwen' },
  { value: 'qwen3-30b-a3b', label: 'Qwen3 30B', group: 'Qwen' },
  // Ollama / Local
  { value: 'ollama/llama3', label: 'Ollama Llama 3', group: 'Ollama' },
  { value: 'ollama/qwen2.5', label: 'Ollama Qwen 2.5', group: 'Ollama' },
  { value: 'ollama/deepseek-r1', label: 'Ollama DeepSeek R1', group: 'Ollama' },
  { value: 'ollama/mistral', label: 'Ollama Mistral', group: 'Ollama' },
  { value: 'ollama/gemma3', label: 'Ollama Gemma 3', group: 'Ollama' },
  // Moonshot / Kimi
  { value: 'moonshot-v1', label: 'Moonshot v1 (Kimi)', group: 'Moonshot' },
  // GLM / Zhipu
  { value: 'glm-4-plus', label: 'GLM-4-Plus (智谱)', group: 'Zhipu' },
  { value: 'glm-4-air', label: 'GLM-4-Air (智谱)', group: 'Zhipu' },
] as const
