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

/**
 * 文献补充材料里的一个附件。
 *
 * `is_sample_hint` 是「这条**可能**是样本信息表」的**提示**，不是分类结果 ——
 * 判据是 caption/文件名里的关键词（server/supplementary.py 的 SAMPLE_HINT），
 * 实测并不可靠：`Table_S9.xlsx` 打开是 motif 表，`mmc2.xlsx` 才是患者信息。
 * 所以 UI 只能拿它来排序和打星，**绝不能用它过滤掉任何一条**
 * （很多论文的 caption 干脆是空的，"Supplemental data" 那种）。
 */
export interface SupplementaryItem {
  name: string
  caption: string
  kind: 'table' | 'file' | 'figure'
  is_sample_hint: boolean
}

/**
 * 为什么没有补充材料。
 *
 * 三种情况对读者的含义完全不同，UI 必须分开说 —— 把「我们没能力检查」
 * 说成「确实没有」是在误导：
 *  · 'no-pmcid' — 该刊未开放全文，我们拿不到，**没检查过**
 *  · 'error'    — 抓取失败（限流/超时），重试可能就有了
 *  · 'none'     — 拿到了全文，里面确实没有附件
 *  · ''         — 有附件，无需提示
 */
export type SupplementaryNote = '' | 'no-pmcid' | 'none' | 'error'

export interface SupplementarySheet {
  name: string
  columns: string[]
  rows: (string | number | null)[][]
}

/** /api/supplementary-table 的响应。失败时只有 error。 */
export interface SupplementaryTable {
  sheets?: SupplementarySheet[]
  truncated?: boolean
  error?: string
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
  /**
   * PMC 编号（后端 pubmed.py 从 EuropePMC 查到的）。
   *
   * 取补充材料内容时要拿它去换，所以必须能传到前端。可选：非 OA 文献
   * 或非 PubMed 数据集没有这个值 —— 那正是 'no-pmcid' 那种状态的来源。
   */
  pmcid?: string
  /**
   * 文献的补充材料清单，以及「没有」的原因。
   *
   * 可选的理由与 PlotResult.gene_resolved 相同：字段出现之前缓存的响应
   * 仍然合法。**但这里多一层语义** —— 对非 PubMed 数据集（PKU/BALF 那种
   * PMID 不是数字的），后端整个不写这两个字段，表示「这压根不是一篇文献，
   * 无从谈起」；而写了字段但 `supplementary: []` 才是「查过，没有」。
   * 前端据此决定是整块不渲染，还是渲染一句说明。
   */
  supplementary?: SupplementaryItem[]
  supplementary_note?: SupplementaryNote
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
  /**
   * 摘要。**可能为 null**。
   *
   * 摘要是这个页面上唯一要经公司代理发外部 HTTP 的字段，冷缓存时实测 4s~125s
   * （BUG_LOG B35），而 stats 走本地 scanner 缓存只要毫秒级。两者挤在同一个
   * 响应里时，慢的那一头会把整个「点进数据集」页面拖垮。
   * 所以 /api/analysis-info 只带回进程内**已经缓存**的摘要，没有就给 null，
   * 由 fetchAbstract 另发一次请求补上。
   */
  abstract: AbstractInfo | null
  /**
   * 服务端是否已拿到完整摘要。false 不代表失败，只代表还该问一次
   * /api/abstract。可选的理由与 PlotResult.gene_resolved 相同：
   * 字段出现之前产生的响应仍然合法。
   */
  abstract_ready?: boolean
  stats: AnalysisStats
}

/** GET /api/abstract 的响应 —— 按需抓取的摘要。 */
export interface AbstractResponse {
  pmid: string
  abstract: AbstractInfo | null
  abstract_ready: boolean
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
  case_group?: string
  control_group?: string
  disease?: string
  error?: string
}

export interface BulkDiseasesResult {
  diseases: string[]
  /** Obs column usable as an alternative panel x-axis (organ axis), e.g. 'Tissue'. */
  tissue_column?: string | null
  error?: string
}

export interface BulkGroupsResult {
  groups: string[]
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
  /** Present instead of the matrices when the request could not be answered. */
  error?: string
}

/**
 * The p-value grid the UMAP tab shows under "Cell Type Ratio by Group".
 *
 * Deliberately NOT `MutestResult`: `/api/umap-ratio-plots` builds it in
 * `server/analysis/plots.py:899` as `{pairs, cell_types, matrix}`, whereas
 * `/api/per-sample-mutest` returns `mean_matrix`/`pct_matrix`. The two payloads
 * share `pairs` and `cell_types` and nothing else. Typing this as
 * `MutestResult` (as it was) made `pairwise.matrix` invisible to the compiler,
 * which is why the four reads below it were written as `as any` — and why
 * renaming either field on the backend would have failed silently instead of
 * at the type check.
 */
export interface PairwisePValues {
  pairs: string[]
  cell_types: string[]
  matrix: (number | null)[][]
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

export interface FisherResultRow {
  gene: string
  pair: string
  pvals: (number | null)[]
}

export interface FisherResult {
  cell_types: string[]
  rows: FisherResultRow[]
}

/** How a Merge-gene member set collapses into the synthetic gene 'M'.
 *  'or'  = union — M positive if ANY member is (historical default).
 *  'and' = intersection — M positive only if EVERY member is. */
export type MergeOp = 'or' | 'and'

export interface AggregateTable {
  rows: AggregateRow[]
  n_rows: number
  groups: string[]
  fisher: FisherResult
  /** Present instead of the payload when the backend fails the request. */
  error?: string
  /** Merge members that resolved to real var names (post-dedup). */
  gene2_resolved?: string[]
  /** Merge members the user typed that matched nothing — surfaced as a warning. */
  gene2_unresolved?: string[]
}

export interface PlotResult {
  image?: string
  error?: string
  width?: number
  height?: number
  /**
   * The var name the backend actually plotted for the primary gene.
   *
   * It can differ from what was asked for: an unknown token is resolved by
   * substring (server/analysis/utils.py:124), so "CD3" quietly plots "ABCD3".
   * The plot looks ordinary either way, so this is what lets the UI say which
   * gene the reader is really looking at. Optional — responses cached before
   * the backend reported it are still valid, and mean "not stated".
   */
  gene_resolved?: string
  /** Merge members that resolved to real var names (post-dedup). */
  gene2_resolved?: string[]
  /** Merge members the user typed that matched nothing — surfaced as a warning. */
  gene2_unresolved?: string[]
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
  pairwise?: PairwisePValues
  n_cell_types?: number
  n_samples?: number
  low_cell_pct?: number
  /** Set instead of the plots when the dataset could not be read. */
  error?: string
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

// ─── 公司内网 LLM 网关默认值（三处 LMM 面板共用） ──────────────
// 之前 FreeAnalysisTab:11 / LiteratureTab:11 各抄了一份 DEFAULT_CONFIG，
// 两份字面量已经开始各自演化（drug 页那个还漏了 apiKey）。
// 收敛成一处，改网关地址只需要改这里。
//
// 这里的 apiKey 是**内网网关**的 key（ai.dgtmeta.com），本项目面向公司内部使用，
// 已由使用者确认无需处理。若要对外发布，这里必须换成环境变量注入。
export const COMPANY_LLM_MODEL = 'Qwen3.5-397B-A17B-FP8-Thinking'
export const COMPANY_LLM_BASE = 'http://llm-gateway.ai.dgtmeta.com/v1'

export const DEFAULT_LLM_CONFIG: LLMConfig = {
  model: COMPANY_LLM_MODEL,
  apiKey: 'sk-fdQEp3ZkOOxz50BVJWbhGaHzHHIiBztLPtBTDyxFwbPMLcfo',
  baseUrl: COMPANY_LLM_BASE,
  temperature: 0.7,
}

export interface ChatResponse {
  content?: string
  error?: string
  tool_results?: ToolResult[]
  iterations?: number
}

// ─── v4: Drug Discovery Pipeline ─────────────────────────────
// 字段名与 server/drug_stages.py 的 stages_payload() 一一对应；
// 后端是唯一数据源，前端不重复维护阶段定义。

export interface DrugStage {
  id: string
  order: number
  label: string
  summary: string
  skills: string[]
  /** 本阶段做不到什么。空字符串表示没有特别要声明的边界。 */
  gap: string
}

export interface DrugStagesPayload {
  stages: DrugStage[]
  /** 每个阶段都可调用的常驻 skill，不属于任何单个阶段。 */
  baseSkills: string[]
  /** 整条通路共同的能力缺口（写不了 IND 申报材料等），页面上常驻展示。 */
  capabilityNote: string
}

/** 某个阶段在本次运行中的状态。前端据此渲染进度。 */
export type DrugStageStatus = 'pending' | 'running' | 'ok' | 'error'

export interface DrugStageProgress {
  stageId: string
  label: string
  status: DrugStageStatus
  /** 在整个所选序列里的位置，从 0 开始（后端从 1 开始，这里减过了）。 */
  index: number
  total: number
  elapsedMs?: number
  error?: string
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
