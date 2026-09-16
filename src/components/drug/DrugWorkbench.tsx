import { useState, useCallback, useRef, useEffect } from 'react'
import {
  Send, StopCircle, Settings2, Trash2, BookOpen, Database, AlertTriangle, X,
} from 'lucide-react'
import StageSelector from './StageSelector'
import ChatPanel from '../analysis/ChatPanel'
import ToolResultsPanel from '../analysis/ToolResultsPanel'
import SkillDetailModal from '../analysis/SkillDetailModal'
import LLMConfigPanel from '../analysis/LLMConfigPanel'
import DragHandle from '../analysis/DragHandle'
import { fetchDrugStages, runDrugPipelineStreaming } from '../../api/drug'
import { fetchDatasets } from '../../api/datasets'
import {
  toggleStage, selectAllStages, orderSelected,
  loadSelection, saveSelection, initProgress, applyStageEvent, progressSummary,
} from './stageSelection'
import type {
  DatasetInfo, DrugStage, DrugStageProgress, LLMConfig, ChatMessage, ToolResult,
} from '../../api/types'
import { DEFAULT_LLM_CONFIG } from '../../api/types'

/**
 * 药物发现工作台。
 *
 * 与分析页的 Free Analysis 是同一套交互骨架（左侧内容 + 右侧工具结果），
 * 但有三处刻意的不同：
 *
 *   1. **阶段化**。一次运行 = 多个阶段，每个阶段是独立的 agent 循环，
 *      事件带 stage_id。消息流按阶段分节，不是一条连续对话。
 *   2. **没有数据集也能跑**。分析页的入口在未挂载数据集时直接报错
 *      （FreeAnalysisTab.tsx:106），而药物页的主用例是「查一个靶点」，
 *      数据集是可选的补充上下文。
 *   3. **问句是「靶点 / 化合物 / 适应症」而不是「关于这份数据的问题」**。
 */

// 与分析页共用同一个 localStorage 键 —— 用户在任一页配好的网关/模型，
// 另一页直接可用，不会出现「分析页能跑、药物页说没配 key」的分裂。
const CONFIG_STORAGE_KEY = 'gensci_omics_llm_config'

function loadConfig(): LLMConfig {
  try {
    const saved = localStorage.getItem(CONFIG_STORAGE_KEY)
    if (saved) return { ...DEFAULT_LLM_CONFIG, ...JSON.parse(saved) }
  } catch { /* 坏配置退回默认 */ }
  return { ...DEFAULT_LLM_CONFIG }
}

const EXAMPLE_QUERIES = [
  'EGFR 在非小细胞肺癌中的成药性评估',
  '评估 metformin 的老药新用潜力',
  'KRAS G12C 抑制剂的耐药机制与联合用药策略',
  'GLP1R 激动剂的安全性画像与监管状态',
]

export default function DrugWorkbench() {
  const [stages, setStages] = useState<DrugStage[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [capabilityNote, setCapabilityNote] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)

  const [query, setQuery] = useState('')
  const [progress, setProgress] = useState<DrugStageProgress[] | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)

  const [config, setConfig] = useState<LLMConfig>(loadConfig)
  const [showConfig, setShowConfig] = useState(false)
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [toolsOpen, setToolsOpen] = useState(true)
  const [toolsW, setToolsW] = useState(320)

  const [datasets, setDatasets] = useState<DatasetInfo[]>([])
  const [showDatasets, setShowDatasets] = useState(false)
  const [realPath, setRealPath] = useState('')

  const abortRef = useRef<AbortController | null>(null)
  // 用 ref 而不是 state：事件回调在 await 的循环里读它，state 的更新
  // 是批处理的，读到的会是旧值。
  const toolResultsRef = useRef<ToolResult[]>([])

  // 阶段注册表来自后端 —— 加阶段只改 server/drug_stages.py，前端不用动。
  useEffect(() => {
    fetchDrugStages()
      .then(payload => {
        setStages(payload.stages)
        setCapabilityNote(payload.capabilityNote)
        const restored = loadSelection(payload.stages)
        // 首次访问（没存过）默认勾选全部 —— 让用户看到整条通路是什么样，
        // 再自己减，比面对 6 个空复选框更容易理解这个页面。
        setSelected(restored.length ? restored : selectAllStages(payload.stages))
      })
      .catch((e: unknown) => {
        setLoadError(e instanceof Error ? e.message : '无法加载阶段列表')
      })
  }, [])

  const toggle = useCallback((id: string) => {
    setSelected(prev => {
      const next = toggleStage(prev, id)
      saveSelection(next)
      return next
    })
  }, [])

  const selectAll = useCallback(() => {
    const next = selectAllStages(stages)
    setSelected(next); saveSelection(next)
  }, [stages])

  const clearAll = useCallback(() => {
    setSelected([]); saveSelection([])
  }, [])

  const saveConfig = useCallback((c: LLMConfig) => {
    setConfig(c)
    try { localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(c)) } catch { /* ignore */ }
  }, [])

  const openDatasets = useCallback(() => {
    setShowDatasets(true)
    if (datasets.length === 0) {
      fetchDatasets().then(setDatasets).catch(() => setDatasets([]))
    }
  }, [datasets.length])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setRunning(false)
    setStatus(null)
  }, [])

  const handleRun = useCallback(async (rawQuery: string) => {
    const q = rawQuery.trim()
    if (!q || running) return
    if (selected.length === 0) { setError('至少选择一个阶段。'); return }
    if (!config.apiKey && !config.baseUrl.includes('localhost') && !config.baseUrl.includes('127.0.0.1')) {
      setError('请先在 LLM Settings 里配置 API key。'); return
    }

    const ordered = orderSelected(selected, stages)
    setMessages([])
    setProgress(initProgress(stages, selected))
    toolResultsRef.current = []
    setError(null)
    setStatus(null)
    setRunning(true)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await runDrugPipelineStreaming({
        query: q,
        stageIds: ordered,
        config,
        realPath,
        signal: controller.signal,
        onEvent: (event, data) => {
          const d = (data ?? {}) as Record<string, unknown>

          setProgress(prev => (prev ? applyStageEvent(prev, event, data) : prev))

          if (event === 'stage_start') {
            const label = typeof d.label === 'string' ? d.label : ''
            const index = typeof d.index === 'number' ? d.index : 0
            const total = typeof d.total === 'number' ? d.total : ordered.length
            // 每段开头插一条 user 消息当分节标题，让消息流能看出
            // 「这段的结论属于哪一阶段」—— 否则 6 段连排会读成一整篇。
            setMessages(prev => [...prev,
              { role: 'user', content: `▶ 阶段 ${index}/${total}：${label}` },
              { role: 'assistant', content: '', tool_results: [] },
            ])
            setStatus(null)
          }

          if (event === 'status') {
            setStatus(typeof d.message === 'string' ? d.message : null)
          } else if (event === 'message') {
            const chunk = typeof d.content === 'string' ? d.content : ''
            if (chunk) {
              setMessages(prev => {
                const next = [...prev]
                const last = next[next.length - 1]
                if (last?.role === 'assistant') {
                  next[next.length - 1] = { ...last, content: last.content + chunk }
                }
                return next
              })
            }
          } else if (event === 'tool_result') {
            toolResultsRef.current = [...toolResultsRef.current, d as ToolResult]
            setMessages(prev => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (last?.role === 'assistant') {
                next[next.length - 1] = { ...last, tool_results: toolResultsRef.current }
              }
              return next
            })
          } else if (event === 'error') {
            setError(typeof d.error === 'string' ? d.error : '运行出错')
          }
        },
      })
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') setError(err.message)
    } finally {
      setRunning(false)
      setStatus(null)
      abortRef.current = null
    }
  }, [running, selected, stages, config, realPath])

  const handleInputSend = () => {
    const q = query.trim()
    if (!q) return
    handleRun(q)
    setQuery('')
  }

  const handleClear = () => {
    setMessages([]); setProgress(null); setError(null)
    toolResultsRef.current = []
  }

  const hasOutput = messages.length > 0
  const orderedLabels = stages.filter(s => selected.includes(s.id))

  return (
    <div className="h-full flex flex-col bg-surface rounded-xl border border-border-light shadow-card overflow-hidden">
      {/* ── 顶栏 ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-light shrink-0">
        <div className="flex items-center gap-1">
          <button onClick={() => setShowConfig(!showConfig)}
            className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors ${
              showConfig ? 'bg-blue-50 text-brand' : 'text-text-muted hover:text-text-secondary hover:bg-surface-raised'
            }`}>
            <Settings2 className="w-3 h-3" />{showConfig ? 'Hide Config' : 'LLM Settings'}
          </button>
          <button onClick={openDatasets}
            className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors ${
              realPath ? 'bg-blue-50 text-brand' : 'text-text-muted hover:text-text-secondary hover:bg-surface-raised'
            }`}>
            <Database className="w-3 h-3" />{realPath ? realPath.split('/').pop() : 'Attach dataset'}
          </button>
          {hasOutput && (
            <button onClick={handleClear}
              className="flex items-center gap-1 text-[10px] text-text-muted hover:text-error px-2 py-1 rounded hover:bg-surface-raised transition-colors">
              <Trash2 className="w-3 h-3" />Clear
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {progress && <span className="text-[10px] text-text-muted">{progressSummary(progress)}</span>}
          <span className="text-[10px] text-text-muted">{config.model}</span>
        </div>
      </div>

      {showConfig && (
        <div className="shrink-0 border-b border-border-light px-3 py-2 bg-surface-raised/50">
          <LLMConfigPanel config={config} onChange={saveConfig} />
        </div>
      )}

      {/* ── 数据集选择（可选） ───────────────────────────────── */}
      {showDatasets && (
        <div className="shrink-0 border-b border-border-light px-3 py-2 bg-surface-raised/50">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-text-muted">
              挂载数据集（可选）—— 挂上后 agent 可读取表达数据作为补充证据
            </span>
            <button onClick={() => setShowDatasets(false)} className="text-text-muted hover:text-text-primary">
              <X className="w-3 h-3" />
            </button>
          </div>
          <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
            <button onClick={() => setRealPath('')}
              className={`text-[10px] px-2 py-1 rounded border transition-colors ${
                realPath === '' ? 'border-brand text-brand bg-brand-bg' : 'border-border-light text-text-muted hover:text-text-secondary'
              }`}>
              不挂载
            </button>
            {datasets.map(ds => (
              <button key={ds.real_path} onClick={() => setRealPath(ds.real_path)}
                title={ds.real_path}
                className={`text-[10px] px-2 py-1 rounded border transition-colors max-w-[220px] truncate ${
                  realPath === ds.real_path ? 'border-brand text-brand bg-brand-bg' : 'border-border-light text-text-muted hover:text-text-secondary'
                }`}>
                {ds.tissue} · {ds.disease} · {ds.pmid}
              </button>
            ))}
            {datasets.length === 0 && <span className="text-[10px] text-text-muted py-1">加载中…</span>}
          </div>
        </div>
      )}

      {/* ── 能力边界（常驻） ─────────────────────────────────── */}
      {capabilityNote && (
        <div className="shrink-0 flex items-start gap-1.5 px-3 py-1.5 bg-amber-50 border-b border-amber-200">
          <AlertTriangle className="w-3 h-3 text-amber-600 shrink-0 mt-0.5" />
          <span className="text-[9px] text-amber-800 leading-relaxed">{capabilityNote}</span>
        </div>
      )}

      {loadError && (
        <div className="shrink-0 px-3 py-2 text-[11px] text-error bg-error-bg border-b border-border-light">
          无法加载阶段列表：{loadError}（后端未启动？）
        </div>
      )}

      {/* ── 主体 ─────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 flex flex-row">
        {/* 左：阶段选择 */}
        <div className="w-[260px] shrink-0 overflow-y-auto border-r border-border-light px-3 py-3">
          <StageSelector
            stages={stages}
            selected={selected}
            onToggle={toggle}
            onSelectAll={selectAll}
            onClear={clearAll}
            progress={progress}
            running={running}
            onShowSkill={setSelectedSkill}
          />
        </div>

        {/* 中：对话 / 空态 */}
        <div className="flex-1 flex flex-col min-w-0">
          {hasOutput ? (
            <div className="flex-1 min-h-0">
              <ChatPanel messages={messages} loading={running} error={error} status={status} />
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto px-3 py-3">
              <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 rounded-xl p-4">
                <h2 className="text-sm font-bold text-text-primary mb-1">Drug Discovery Workbench</h2>
                <p className="text-[11px] text-text-secondary leading-relaxed mb-3">
                  按临床前研究通路分 6 个阶段。勾选你要跑的阶段，Agent 会按顺序推进，
                  每一阶段的结论会带进下一阶段作为上下文。所有数据来自公开数据库
                  （ChEMBL / Open Targets / FAERS / PubChem 等），不产生实验数据。
                </p>

                <div className="mb-3">
                  <div className="text-[9px] text-text-muted mb-1">
                    将按此顺序运行 {orderedLabels.length} 个阶段：
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {orderedLabels.map(s => (
                      <span key={s.id}
                        className="text-[9px] text-brand bg-surface px-1.5 py-0.5 rounded border border-blue-200">
                        {s.order}. {s.label}
                      </span>
                    ))}
                    {orderedLabels.length === 0 && (
                      <span className="text-[9px] text-error">尚未选择任何阶段</span>
                    )}
                  </div>
                </div>

                <div>
                  <div className="text-[9px] text-brand font-medium mb-1.5">试试这些</div>
                  <div className="flex flex-wrap gap-1.5">
                    {EXAMPLE_QUERIES.map(ex => (
                      <button key={ex} onClick={() => handleRun(ex)}
                        className="text-[10px] bg-surface text-text-muted hover:text-brand hover:border-blue-300 border border-border-light px-2 py-1 rounded-lg transition-colors">
                        💊 {ex}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 右：工具结果 */}
        {hasOutput && toolsOpen && (
          <DragHandle
            orientation="vertical"
            onDrag={(d) => setToolsW(prev => Math.max(200, Math.min(window.innerWidth * 0.4, prev + d)))}
          />
        )}
        {hasOutput && (
          <div className="shrink-0 overflow-hidden transition-all duration-200"
            style={{ width: toolsOpen ? toolsW : 0 }}>
            <ToolResultsPanel messages={messages} loading={running} />
          </div>
        )}
      </div>

      {/* ── 输入栏 ───────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border-light bg-surface px-3 py-2">
        <div className="flex items-end gap-2">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleInputSend() }
            }}
            placeholder="输入靶点 / 化合物 / 适应症，例如 EGFR、metformin…"
            rows={1}
            disabled={running}
            className="flex-1 text-xs border border-border-light rounded-lg px-3 py-2 outline-none focus:border-blue-400 resize-none placeholder:text-text-muted max-h-20 disabled:bg-surface-muted"
          />
          {running ? (
            <button onClick={handleStop}
              className="flex items-center gap-1 text-[10px] bg-error-bg text-error px-2.5 py-2 rounded-lg hover:bg-red-100 transition-colors shrink-0">
              <StopCircle className="w-3.5 h-3.5" /> Stop
            </button>
          ) : (
            <button onClick={handleInputSend} disabled={!query.trim() || selected.length === 0}
              className="flex items-center gap-1 text-[10px] bg-brand text-white px-2.5 py-2 rounded-lg hover:bg-blue-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0">
              <Send className="w-3.5 h-3.5" /> 运行 {orderedLabels.length} 阶段
            </button>
          )}
        </div>
        {!toolsOpen && hasOutput && (
          <button onClick={() => setToolsOpen(true)}
            className="mt-1 flex items-center gap-1 text-[9px] text-text-muted hover:text-brand">
            <BookOpen className="w-3 h-3" /> 显示工具调用记录
          </button>
        )}
      </div>

      <SkillDetailModal skillName={selectedSkill} onClose={() => setSelectedSkill(null)} />
    </div>
  )
}
