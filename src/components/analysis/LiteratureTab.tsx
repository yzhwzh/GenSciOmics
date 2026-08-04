import { useState, useCallback, useRef, useEffect } from 'react'
import { BookOpen, Settings2, Trash2, Send, StopCircle, Search, FileText, Network, BarChart3, Lightbulb, ExternalLink, ChevronRight, ChevronLeft } from 'lucide-react'
import LLMConfigPanel from './LLMConfigPanel'
import ChatPanel from './ChatPanel'
import ToolResultsPanel from './ToolResultsPanel'
import SkillDetailModal from './SkillDetailModal'
import DragHandle from './DragHandle'
import { sendLiteratureMessageStreaming } from '../../api/analysis'
import type { ChatMessage, LLMConfig, ToolResult, SkillDef } from '../../api/types'

const DEFAULT_CONFIG: LLMConfig = {
  model: 'Qwen3.5-397B-A17B-FP8-Thinking',
  apiKey: 'sk-fdQEp3ZkOOxz50BVJWbhGaHzHHIiBztLPtBTDyxFwbPMLcfo',
  baseUrl: 'http://llm-gateway.ai.dgtmeta.com/v1',
  temperature: 0.7,
}

function loadConfig(): LLMConfig {
  try {
    const saved = localStorage.getItem('gensci_lit_config')
    if (saved) return { ...DEFAULT_CONFIG, ...JSON.parse(saved) }
  } catch { /* ignore */ }
  return DEFAULT_CONFIG
}

const EXAMPLE_PROMPTS = [
  'What research has been done on this tissue/disease?',
  'Find publicly available single-cell datasets for this disease',
  'Compare the key findings from recent studies',
  'Which datasets are NOT on our platform? I want to request new data',
  'Give me a comprehensive literature review with comparative conclusions',
]

const FEATURES = [
  { icon: Search, text: 'Search PubMed, Crossref, arXiv simultaneously' },
  { icon: FileText, text: 'Find downloadable datasets (GEO, ArrayExpress)' },
  { icon: Network, text: 'Identify research gaps & data not on GenSci' },
  { icon: BarChart3, text: 'Generate comparative reviews & conclusions' },
  { icon: Lightbulb, text: 'Request new data: yuanwuzhou@genscigroup.com' },
]

const STORAGE_PREFIX = 'gensci_lit_msgs_'

function loadMessages(context: string): ChatMessage[] {
  try {
    const saved = sessionStorage.getItem(STORAGE_PREFIX + context)
    if (saved) return JSON.parse(saved)
  } catch { /* ignore */ }
  return []
}

function saveMessages(context: string, msgs: ChatMessage[]) {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + context, JSON.stringify(msgs))
  } catch { /* ignore */ }
}

export default function LiteratureTab({ context }: { context: string }) {
  const [config, setConfig] = useState<LLMConfig>(loadConfig)
  const [showConfig, setShowConfig] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [toolsOpen, setToolsOpen] = useState(true)
  const [toolsW, setToolsW] = useState(280)
  const [showSkills, setShowSkills] = useState(false)
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [skills, setSkills] = useState<SkillDef[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const skillsRef = useRef<HTMLDivElement>(null)

  // Fetch Light skills only
  useEffect(() => {
    fetch('/api/skills')
      .then(r => r.json())
      .then((data: SkillDef[]) => {
        const filtered = data.filter(s => s.name.startsWith('light-'))
        setSkills(filtered)
      })
      .catch(() => {})
  }, [])

  // Reload messages when context stabilizes (fixes loss on navigate-back)
  useEffect(() => {
    const saved = loadMessages(context)
    if (saved.length > 0) setMessages(saved)
  }, [context])

  // Persist messages to sessionStorage on change
  useEffect(() => {
    if (messages.length > 0) saveMessages(context, messages)
  }, [context, messages])

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
    try { localStorage.setItem('gensci_lit_config', JSON.stringify(c)) } catch { /* ignore */ }
  }, [])

  const handleSend = useCallback(async (text: string) => {
    if (loading) return
    if (!config.apiKey && !config.baseUrl.includes('localhost') && !config.baseUrl.includes('127.0.0.1')) { setError('Please configure your API key in LLM Settings.'); return }

    const userMsg: ChatMessage = { role: 'user', content: text }
    const updatedMessages = [...messages, userMsg]
    setMessages(updatedMessages)
    setLoading(true)
    setError(null)
    setStatusMsg('Searching...')

    // Add placeholder assistant message for streaming
    setMessages(prev => [...prev, { role: 'assistant', content: '', tool_results: [] }])

    const toolResults: ToolResult[] = []
    const abortController = new AbortController()
    abortRef.current = abortController

    try {
      await sendLiteratureMessageStreaming(updatedMessages, config, context, (event, data) => {
        if (event === 'message') {
          setStatusMsg(null)
          const d = data as { content: string }
          setMessages(prev => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = { ...last, content: last.content + d.content }
            }
            return next
          })
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
        } else if (event === 'status') {
          const d = data as { stage: string; message: string }
          setStatusMsg(d.message || null)
        } else if (event === 'error') {
          const d = data as { error: string }
          setError(d.error || 'An error occurred')
        }
      }, abortController.signal)
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') setError(err.message)
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }, [context, config, messages, loading])

  const handleStop = useCallback(() => { abortRef.current?.abort(); setLoading(false) }, [])

  const handleClear = useCallback(() => {
    setMessages([]); setError(null); setStatusMsg(null)
    try { sessionStorage.removeItem(STORAGE_PREFIX + context) } catch { /* ignore */ }
  }, [context])

  const handleInputSend = () => {
    const msg = input.trim()
    if (!msg || loading) return
    if (!config.apiKey && !config.baseUrl.includes('localhost') && !config.baseUrl.includes('127.0.0.1')) { setError('Please configure your API key in LLM Settings.'); return }
    handleSend(msg)
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleInputSend() }
  }

  const hasChat = messages.length > 0

  return (
    <div className="h-full flex flex-col bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-1">
          <button onClick={() => setShowConfig(!showConfig)}
            className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors ${
              showConfig ? 'bg-emerald-50 text-emerald-600' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
            }`}>
            <Settings2 className="w-3 h-3" />{showConfig ? 'Hide Config' : 'LLM Settings'}
          </button>
          {hasChat && (
            <button onClick={handleClear}
              className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-red-500 px-2 py-1 rounded hover:bg-gray-50 transition-colors">
              <Trash2 className="w-3 h-3" />Clear
            </button>
          )}

          {/* Light Skills button */}
          <div className="relative" ref={skillsRef}>
            <button onClick={() => setShowSkills(!showSkills)}
              className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors ${
                showSkills ? 'bg-emerald-50 text-emerald-600' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
              }`}>
              <BookOpen className="w-3 h-3" />Light Skills
            </button>

            {showSkills && (
              <div className="absolute top-full left-0 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg z-40 max-h-80 overflow-y-auto">
                <div className="px-3 py-1.5 border-b border-gray-100">
                  <span className="text-[9px] font-semibold text-gray-400 uppercase tracking-wider">Light Skills</span>
                </div>
                {skills.map(s => (
                  <button key={s.name} onClick={() => { setSelectedSkill(s.name); setShowSkills(false) }}
                    className="w-full text-left px-3 py-1.5 text-[11px] text-gray-600 hover:bg-emerald-50 hover:text-emerald-600 transition-colors border-b border-gray-50 last:border-b-0">
                    <div className="font-medium">{s.name}</div>
                    {s.description && <div className="text-[9px] text-gray-400 truncate">{s.description}</div>}
                  </button>
                ))}
                {skills.length === 0 && (
                  <div className="px-3 py-4 text-[10px] text-gray-400 text-center">Loading skills...</div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <BookOpen className="w-3 h-3 text-emerald-500" />
          <span className="text-[10px] text-emerald-600 font-medium">Tissue Workspace</span>
          {hasChat && (
            <button onClick={() => setToolsOpen(!toolsOpen)}
              className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-600 px-1.5 py-1 rounded hover:bg-gray-50 transition-colors"
              title={toolsOpen ? 'Hide tool results' : 'Show tool results'}>
              {toolsOpen ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
            </button>
          )}
          <span className="text-[9px] text-gray-400 font-mono">{config.model}</span>
        </div>
      </div>

      {/* Config panel */}
      {showConfig && (
        <div className="shrink-0 border-b border-gray-100 px-3 py-2 bg-gray-50/50">
          <LLMConfigPanel config={config} onChange={saveConfig} />
        </div>
      )}

      {/* Main content — flex-row */}
      <div className="flex-1 min-h-0 flex flex-row">
        {/* Left: Chat + info cards */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Info cards — visible only before first message */}
          {!hasChat && (
            <div className="overflow-y-auto">
              <div className="px-3 py-3 space-y-3">
                {/* Context badge */}
                <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 rounded-lg border border-emerald-200">
                  <BookOpen className="w-4 h-4 text-emerald-500 shrink-0" />
                  <span className="text-[11px] text-emerald-700 font-medium">Current context: {context}</span>
                </div>

                {/* Main card */}
                <div className="bg-gradient-to-br from-emerald-50 to-teal-50 border border-emerald-200 rounded-xl p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-100 to-teal-100 flex items-center justify-center ring-1 ring-emerald-200">
                      <BookOpen className="w-4 h-4 text-emerald-600" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-gray-800">Tissue Workspace</h2>
                      <p className="text-[9px] text-gray-400 font-mono">light-literature-search · multi-source</p>
                    </div>
                  </div>
                  <p className="text-[11px] text-gray-600 leading-relaxed mb-3">
                    Multi-source literature search with Light AI skills.
                    Search papers, datasets, patents, and more.
                  </p>

                  {/* Feature list */}
                  <div className="space-y-1.5 mb-3">
                    {FEATURES.map((f, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <div className="w-5 h-5 rounded bg-white/80 flex items-center justify-center shrink-0">
                          <f.icon className="w-3 h-3 text-emerald-500" />
                        </div>
                        <span className="text-[10px] text-gray-600">{f.text}</span>
                      </div>
                    ))}
                  </div>

                  {/* Example prompts */}
                  <div>
                    <div className="text-[9px] text-emerald-500 font-medium mb-1.5">Example prompts</div>
                    <div className="flex flex-wrap gap-1.5">
                      {EXAMPLE_PROMPTS.map((ex, i) => (
                        <button key={i} onClick={() => handleSend(ex)}
                          className="text-[10px] bg-white text-gray-500 hover:text-emerald-600 hover:border-emerald-300 border border-gray-200 px-2 py-1 rounded-lg transition-colors">
                          💡 {ex}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Data request info */}
                <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
                  <div className="flex items-center gap-2 mb-1">
                    <ExternalLink className="w-3.5 h-3.5 text-amber-500" />
                    <span className="text-[11px] font-semibold text-amber-700">Need data not on GenSci?</span>
                  </div>
                  <p className="text-[10px] text-amber-600 leading-relaxed">
                    If you find publicly available datasets that are not yet on our platform,
                    email us at <strong className="text-amber-800">chenyunqin01@genscigroup.com</strong> or <strong className="text-amber-800">yuanwuzhou@genscigroup.com</strong> with the details.
                    Our team will process, clean, and upload the data for analysis.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Error message */}
          {error && hasChat && (
            <div className="shrink-0 px-3 py-2">
              <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                <p className="text-[11px] text-red-600">{error}</p>
              </div>
            </div>
          )}

          {/* Chat area */}
          <div className={hasChat ? 'flex-1 min-h-0' : 'hidden'}>
            <ChatPanel messages={messages} loading={loading} error={error} />
          </div>
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

      {/* Input bar */}
      <div className="shrink-0 border-t border-gray-200 bg-white px-3 py-2">
        <div className="flex items-end gap-2">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
            placeholder="Search literature or ask about research..." rows={1}
            className="flex-1 text-xs border border-gray-200 rounded-lg px-3 py-2 outline-none focus:border-emerald-400 resize-none placeholder:text-gray-300 max-h-20" />
          {loading ? (
            <button onClick={handleStop}
              className="flex items-center gap-1 text-[10px] bg-red-50 text-red-500 px-2.5 py-2 rounded-lg hover:bg-red-100 transition-colors shrink-0">
              <StopCircle className="w-3.5 h-3.5" /> Stop
            </button>
          ) : (
            <button onClick={handleInputSend} disabled={!input.trim()}
              className="flex items-center gap-1 text-[10px] bg-emerald-500 text-white px-2.5 py-2 rounded-lg hover:bg-emerald-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0">
              <Send className="w-3.5 h-3.5" /> Send
            </button>
          )}
        </div>
      </div>

      {/* Skill Detail Modal */}
      <SkillDetailModal skillName={selectedSkill} onClose={() => setSelectedSkill(null)} />
    </div>
  )
}
