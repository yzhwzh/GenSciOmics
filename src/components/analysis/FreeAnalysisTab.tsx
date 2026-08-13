import { useState, useCallback, useRef, useEffect } from 'react'
import { Settings2, Trash2, Send, StopCircle, BookOpen, ChevronRight, ChevronLeft, BarChart3, Dna, FlaskConical, Table2, Network } from 'lucide-react'
import LLMConfigPanel from './LLMConfigPanel'
import ChatPanel from './ChatPanel'
import ToolResultsPanel from './ToolResultsPanel'
import SkillDetailModal from './SkillDetailModal'
import DragHandle from './DragHandle'
import { sendChatMessageStreaming } from '../../api/analysis'
import type { ChatMessage, LLMConfig, ToolResult, SkillDef } from '../../api/types'

const DEFAULT_CONFIG: LLMConfig = {
  model: 'Qwen3.5-397B-A17B-FP8-Thinking',
  apiKey: 'sk-fdQEp3ZkOOxz50BVJWbhGaHzHHIiBztLPtBTDyxFwbPMLcfo',
  baseUrl: 'http://llm-gateway.ai.dgtmeta.com/v1',
  temperature: 0.7,
}

const COMPANY_MODEL = 'Qwen3.5-397B-A17B-FP8-Thinking'
const COMPANY_BASE = 'http://llm-gateway.ai.dgtmeta.com/v1'

function loadConfig(): LLMConfig {
  try {
    const saved = localStorage.getItem('gensci_omics_llm_config')
    if (saved) return { ...DEFAULT_CONFIG, ...JSON.parse(saved) }
  } catch { /* ignore */ }
  return { ...DEFAULT_CONFIG }
}

function isCompanyConfig(c: LLMConfig): boolean {
  return c.model === COMPANY_MODEL && c.baseUrl === COMPANY_BASE
}

export default function FreeAnalysisTab({ realPath, omicsType = 'scRNA' }: { realPath: string; omicsType?: string }) {
  const [config, setConfig] = useState<LLMConfig>(loadConfig)
  const [showConfig, setShowConfig] = useState(false)
  const [input, setInput] = useState('')
  const storageKey = `gensci_free_msgs_${realPath}`
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const saved = sessionStorage.getItem(storageKey)
      if (saved) return JSON.parse(saved)
    } catch { /* ignore */ }
    return []
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toolsOpen, setToolsOpen] = useState(true)
  const [toolsW, setToolsW] = useState(280)
  const [showSkills, setShowSkills] = useState(false)
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [skills, setSkills] = useState<SkillDef[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const skillsRef = useRef<HTMLDivElement>(null)

  // Fetch skills list — only analysis-related skills (no system tools or Light skills)
  const isBulk = omicsType === 'BulkRNA'
  useEffect(() => {
    fetch('/api/skills')
      .then(r => r.json())
      .then((data: SkillDef[]) => {
        const filtered = data.filter(s =>
          isBulk
            ? s.name.startsWith('bulk-') || s.name === 'statistical-analysis'
            : s.name.startsWith('single-') || s.name === 'statistical-analysis'
        )
        setSkills(filtered)
      })
      .catch(() => {})
  }, [isBulk])

  // Restore messages from sessionStorage when realPath finishes loading
  useEffect(() => {
    if (!realPath) return
    const key = `gensci_free_msgs_${realPath}`
    try {
      const saved = sessionStorage.getItem(key)
      if (saved) {
        const parsed = JSON.parse(saved) as ChatMessage[]
        if (parsed.length > 0) setMessages(parsed)
      }
    } catch { /* ignore */ }
  }, [realPath])

  // Close skills dropdown on outside click
  useEffect(() => {
    if (!showSkills) return
    const onDown = (e: MouseEvent) => {
      if (skillsRef.current && !skillsRef.current.contains(e.target as Node)) {
        setShowSkills(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [showSkills])

  const saveConfig = useCallback((c: LLMConfig) => {
    setConfig(c)
    try { localStorage.setItem('gensci_omics_llm_config', JSON.stringify(c)) } catch { /* ignore */ }
  }, [])

  const handleSend = useCallback(async (text: string) => {
    if (!realPath) { setError('Dataset path not available.'); return }
    if (!config.apiKey && !config.baseUrl.includes('localhost') && !config.baseUrl.includes('127.0.0.1')) { setError('Please configure your API key in LLM Settings.'); return }

    const userMsg: ChatMessage = { role: 'user', content: text }
    const updatedMessages = [...messages, userMsg]
    setMessages(updatedMessages)
    setLoading(true)
    setError(null)

    // Add placeholder assistant message for streaming
    setMessages(prev => [...prev, { role: 'assistant', content: '', tool_results: [] }])

    const toolResults: ToolResult[] = []
    const abortController = new AbortController()
    abortRef.current = abortController

    try {
      await sendChatMessageStreaming(updatedMessages, realPath, config, (event, data) => {
        if (event === 'message') {
          const d = data as { content: string }
          if (d.content) {
            setMessages(prev => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (last && last.role === 'assistant') {
                next[next.length - 1] = { ...last, content: last.content + d.content }
              }
              return next
            })
          }
        } else if (event === 'tool_result') {
          const d = data as ToolResult
          toolResults.push(d)
          setMessages(prev => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = { ...last, tool_results: [...toolResults] }
            }
            return next
          })
        } else if (event === 'error') {
          const d = data as { error: string }
          setError(d.error || 'An error occurred')
        }
      }, abortController.signal, omicsType)
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') setError(err.message)
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }, [realPath, config, messages, omicsType])

  const handleStop = useCallback(() => { abortRef.current?.abort(); setLoading(false) }, [])

  // Persist messages to sessionStorage on change
  useEffect(() => {
    if (messages.length > 0) {
      try { sessionStorage.setItem(storageKey, JSON.stringify(messages)) } catch { /* ignore */ }
    }
  }, [messages, storageKey])

  const handleClear = useCallback(() => {
    setMessages([]); setError(null)
    try { sessionStorage.removeItem(storageKey) } catch { /* ignore */ }
  }, [storageKey])

  const handleInputSend = () => {
    const msg = input.trim()
    if (!msg || loading) return
    handleSend(msg)
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleInputSend() }
  }

  const hasChat = messages.length > 0

  const agentSubtitle = isBulk ? 'bulk RNA · transcriptomics · statistics' : 'single-cell · statistics · visualization'
  const agentDescription = isBulk
    ? 'AI-powered bulk RNA (transcriptomics) analysis. Ask about differential expression, pathway enrichment, co-expression networks, and more.'
    : 'AI-powered single-cell data analysis. Ask questions about gene expression, cell types, statistical comparisons, and more. Uses specialized analysis scripts combined with LLM reasoning.'
  const FEATURES = isBulk ? [
    { icon: BarChart3, text: 'Differential expression + volcano plot' },
    { icon: BookOpen, text: 'Pathway enrichment (GSEA, GO, KEGG)' },
    { icon: Network, text: 'Co-expression network (WGCNA)' },
    { icon: FlaskConical, text: 'Statistical tests (t-test, MWU)' },
    { icon: Table2, text: 'Deconvolution & cell composition' },
    { icon: BarChart3, text: 'Survival & clinical association' },
    { icon: Dna, text: 'PCA / t-SNE / UMAP embedding' },
    { icon: Table2, text: 'Export tables, plots & summaries' },
  ] : [
    { icon: BarChart3, text: 'Gene expression viz (boxplot/barplot)' },
    { icon: Dna, text: 'Find marker genes per cell type' },
    { icon: Network, text: 'Co-expression / Venn / UpSet' },
    { icon: FlaskConical, text: 'Statistical tests (t-test, MWU)' },
    { icon: BookOpen, text: 'Pathway enrichment (GO, KEGG)' },
    { icon: Network, text: 'Gene regulatory network (SCENIC)' },
    { icon: BarChart3, text: 'Cell communication (CellPhoneDB)' },
    { icon: Dna, text: 'Trajectory inference & RNA velocity' },
    { icon: Table2, text: 'Cell type annotation & sub-clustering' },
    { icon: FlaskConical, text: 'Perturbation & cell fate analysis' },
    { icon: BookOpen, text: 'Foundation model (Geneformer, scGPT)' },
    { icon: Table2, text: 'Export tables, plots & summaries' },
  ]
  const EXAMPLE_PROMPTS = isBulk ? [
    'Show TP53 differential expression',
    'Volcano plot for TCGA-BRCA',
    'GSEA on upregulated genes',
    'Co-expression of EGFR and ERBB2',
    'Dataset summary',
  ] : [
    'Show ACE2 expression by CellType',
    'Find markers for Epithelial cells',
    'Co-expression of EGFR, PD1, PSMA',
    't-test between groups for nFeature_RNA',
    'Dataset summary',
  ]

  return (
    <div className="h-full flex flex-col bg-surface rounded-xl border border-border-light shadow-card overflow-hidden">
      {/* ── Header ───────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-light shrink-0">
        <div className="flex items-center gap-1">
          <button onClick={() => setShowConfig(!showConfig)}
            className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors ${
              showConfig ? 'bg-blue-50 text-brand' : 'text-text-muted hover:text-text-secondary hover:bg-surface-raised'
            }`}>
            <Settings2 className="w-3 h-3" />{showConfig ? 'Hide Config' : 'LLM Settings'}
          </button>
          {hasChat && (
            <button onClick={handleClear}
              className="flex items-center gap-1 text-[10px] text-text-muted hover:text-error px-2 py-1 rounded hover:bg-surface-raised transition-colors">
              <Trash2 className="w-3 h-3" />Clear
            </button>
          )}

          {/* Skills button with dropdown */}
          <div className="relative" ref={skillsRef}>
            <button onClick={() => setShowSkills(!showSkills)}
              className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors ${
                showSkills ? 'bg-blue-50 text-brand' : 'text-text-muted hover:text-text-secondary hover:bg-surface-raised'
              }`}>
              <BookOpen className="w-3 h-3" />Skills
            </button>

            {showSkills && (
              <div className="absolute top-full left-0 mt-1 w-56 bg-surface border border-border-light rounded-lg shadow-lg z-40 max-h-80 overflow-y-auto">
                <div className="px-3 py-1.5 border-b border-border-light">
                  <span className="text-[9px] font-semibold text-text-muted uppercase tracking-wider">Available Skills</span>
                </div>
                {skills.map(s => (
                  <button key={s.name} onClick={() => { setSelectedSkill(s.name); setShowSkills(false) }}
                    className="w-full text-left px-3 py-1.5 text-[11px] text-text-secondary hover:bg-surface-muted hover:text-brand transition-colors border-b border-border-light last:border-b-0">
                    <div className="font-medium">{s.name}</div>
                    {s.description && <div className="text-[9px] text-text-muted truncate">{s.description}</div>}
                  </button>
                ))}
                {skills.length === 0 && (
                  <div className="px-3 py-4 text-[10px] text-text-muted text-center">Loading skills...</div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {hasChat && (
            <button onClick={() => setToolsOpen(!toolsOpen)}
              className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text-secondary px-1.5 py-1 rounded hover:bg-surface-raised transition-colors"
              title={toolsOpen ? 'Hide tool results' : 'Show tool results'}>
              {toolsOpen ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
            </button>
          )}
          <span className="text-[10px] text-text-muted">
            {isCompanyConfig(config) ? 'Qwen (Company)' : config.model}
          </span>
          {!isCompanyConfig(config) && (
            <button onClick={() => {
              setConfig({ ...DEFAULT_CONFIG })
              try { localStorage.removeItem('gensci_omics_llm_config') } catch { /* ignore */ }
            }} className="text-[9px] text-brand-gold hover:text-brand ml-1" title="Reset to company default">↩ default</button>
          )}
        </div>
      </div>

      {/* ── Config panel ─────────────────────────────────────── */}
      {showConfig && (
        <div className="shrink-0 border-b border-border-light px-3 py-2 bg-surface-raised/50">
          <LLMConfigPanel config={config} onChange={saveConfig} />
        </div>
      )}

      {/* ── Main content ─────────────────────────────────────── */}
      {!realPath ? (
        <div className="flex-1 flex items-center justify-center text-sm text-text-muted">Select a dataset to begin analysis.</div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-row">
          {/* Left: Chat */}
          <div className="flex-1 flex flex-col min-w-0">
            {hasChat ? (
              <div className="flex-1 min-h-0">
                <ChatPanel messages={messages} loading={loading} error={error} />
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto">
                <div className="px-3 py-3 space-y-3">
                  {/* Dataset context badge */}
                  <div className="flex items-center gap-2 px-3 py-2 bg-blue-50 rounded-lg border border-blue-200">
                    <BarChart3 className="w-4 h-4 text-brand shrink-0" />
                    <span className="text-[11px] text-brand-dark font-medium truncate">Dataset: {realPath.split('/').pop()}</span>
                  </div>

                  {/* Main card */}
                  <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-100 to-indigo-100 flex items-center justify-center ring-1 ring-blue-200">
                        <Dna className="w-4 h-4 text-brand" />
                      </div>
                      <div>
                        <h2 className="text-sm font-bold text-text-primary">GenSci Analysis Agent</h2>
                        <p className="text-[9px] text-text-muted font-mono">{agentSubtitle}</p>
                      </div>
                    </div>
                    <p className="text-[11px] text-text-secondary leading-relaxed mb-3">
                      {agentDescription}
                    </p>

                    {/* Features */}
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 mb-3">
                      {FEATURES.map((f, i) => (
                        <div key={i} className="flex items-center gap-1.5">
                          <div className="w-5 h-5 rounded bg-surface/80 flex items-center justify-center shrink-0">
                            <f.icon className="w-3 h-3 text-brand" />
                          </div>
                          <span className="text-[10px] text-text-secondary">{f.text}</span>
                        </div>
                      ))}
                    </div>

                    {/* Example prompts */}
                    <div>
                      <div className="text-[9px] text-brand font-medium mb-1.5">Try asking</div>
                      <div className="flex flex-wrap gap-1.5">
                        {EXAMPLE_PROMPTS.map((ex, i) => (
                          <button key={i} onClick={() => { handleSend(ex); setInput('') }}
                            className="text-[10px] bg-surface text-text-muted hover:text-brand hover:border-blue-300 border border-border-light px-2 py-1 rounded-lg transition-colors">
                            💡 {ex}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Right: Tool Results Panel */}
          {hasChat && toolsOpen && (
            <DragHandle
              orientation="vertical"
              onDrag={(d) => setToolsW(prev => Math.max(200, Math.min(window.innerWidth * 0.4, prev + d)))}
            />
          )}
          {hasChat && (
            <div
              className="shrink-0 overflow-hidden transition-all duration-200"
              style={{ width: toolsOpen ? toolsW : 0 }}
            >
              <ToolResultsPanel messages={messages} loading={loading} />
            </div>
          )}
        </div>
      )}

      {/* ── Input bar ────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border-light bg-surface px-3 py-2">
        <div className="flex items-end gap-2">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
            placeholder="Ask a question about your data..." rows={1}
            className="flex-1 text-xs border border-border-light rounded-lg px-3 py-2 outline-none focus:border-blue-400 resize-none placeholder:text-text-muted max-h-20" />
          {loading ? (
            <button onClick={handleStop}
              className="flex items-center gap-1 text-[10px] bg-error-bg text-error px-2.5 py-2 rounded-lg hover:bg-red-100 transition-colors shrink-0">
              <StopCircle className="w-3.5 h-3.5" /> Stop
            </button>
          ) : (
            <button onClick={handleInputSend} disabled={!input.trim()}
              className="flex items-center gap-1 text-[10px] bg-brand text-white px-2.5 py-2 rounded-lg hover:bg-blue-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0">
              <Send className="w-3.5 h-3.5" /> Send
            </button>
          )}
        </div>
      </div>

      {/* ── Skill Detail Modal ───────────────────────────────── */}
      <SkillDetailModal skillName={selectedSkill} onClose={() => setSelectedSkill(null)} />
    </div>
  )
}
