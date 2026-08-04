import { useState, useEffect, useRef, useCallback } from 'react'
import { searchGenes } from '../../api/analysis'
import { PALETTE_OPTIONS } from '../../api/types'
import PlotImage from './PlotImage'
import AggregateDetailTable from './AggregateDetailTable'
import FisherTable from './FisherTable'
import DragHandle from './DragHandle'

export default function ExpressionChartContainer({
  realPath,
}: {
  realPath: string
}) {
  const geneSearchRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const toolbarRef = useRef<HTMLDivElement>(null)
  const [metric, setMetric] = useState<'mean_expression' | 'expression_pct'>('mean_expression')
  const [selectedGene, setSelectedGene] = useState(() => {
    try { return sessionStorage.getItem('gensci_agg_gene') ?? 'FAP' } catch { return 'FAP' }
  })
  const [geneSearchInput, setGeneSearchInput] = useState('')
  const [geneSuggestions, setGeneSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [conditionCol, setConditionCol] = useState('Group')
  const [palette, setPalette] = useState('default')
  const [heights, setHeights] = useState([200, 150])
  const [sec3Height, setSec3Height] = useState(200)
  const DRAG_H = 5

  // Persist selectedGene across tab switches
  useEffect(() => {
    try { sessionStorage.setItem('gensci_agg_gene', selectedGene) } catch { /* ignore */ }
  }, [selectedGene])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const total = el.clientHeight
      const tbH = toolbarRef.current?.clientHeight ?? 36
      const used = tbH + (heights[0] ?? 0) + DRAG_H + (heights[1] ?? 0) + DRAG_H
      setSec3Height(Math.max(60, total - used))
    })
    ro.observe(el)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heights[0], heights[1]])

  const adjustHeight = useCallback((idx: number, delta: number) => {
    setHeights(prev => {
      const next = [...prev]
      const minH = 60
      const newCur = Math.max(minH, (next[idx] ?? 0) + delta)
      const actualDelta = newCur - (next[idx] ?? 0)
      if (idx === 0) {
        next[0] = newCur
        next[1] = Math.max(minH, (next[1] ?? 0) - actualDelta)
      } else {
        next[1] = newCur
      }
      return next
    })
  }, [])

  useEffect(() => {
    if (!realPath || geneSearchInput.length < 1) { setGeneSuggestions([]); return }
    const timer = setTimeout(() => {
      searchGenes(realPath, geneSearchInput)
        .then(genes => { setGeneSuggestions(genes); setShowSuggestions(true) })
        .catch(() => setGeneSuggestions([]))
    }, 200)
    return () => clearTimeout(timer)
  }, [realPath, geneSearchInput])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (geneSearchRef.current && !geneSearchRef.current.contains(e.target as Node)) setShowSuggestions(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={containerRef} className="h-full flex flex-col">
      <div ref={toolbarRef} className="flex items-center gap-2 px-3 py-1 border-b border-gray-100 shrink-0 flex-wrap">
        <span className="text-[11px] font-medium text-gray-500">Show</span>
        <div className="flex bg-gray-100 rounded-md p-0.5 text-xs">
          <button onClick={() => setMetric('mean_expression')}
            className={`px-2 py-0.5 rounded transition-colors ${metric === 'mean_expression' ? 'bg-white text-blue-700 shadow-sm font-medium' : 'text-gray-500 hover:text-gray-700'}`}>Mean</button>
          <button onClick={() => setMetric('expression_pct')}
            className={`px-2 py-0.5 rounded transition-colors ${metric === 'expression_pct' ? 'bg-white text-blue-700 shadow-sm font-medium' : 'text-gray-500 hover:text-gray-700'}`}>% Expression</button>
        </div>

        <span className="text-[11px] font-medium text-gray-500 ml-1">Condition</span>
        <select value={conditionCol} onChange={(e) => setConditionCol(e.target.value)}
          className="text-xs border border-gray-200 rounded px-2 py-0.5 bg-white text-gray-700 outline-none focus:border-blue-400">
          <option value="None">None</option>
          <option value="Group">Group</option>
        </select>

        <span className="text-[11px] font-medium text-gray-500 ml-1">Palette</span>
        <select value={palette} onChange={(e) => setPalette(e.target.value)}
          className="text-xs border border-gray-200 rounded px-2 py-0.5 bg-white text-gray-700 outline-none focus:border-blue-400">
          {PALETTE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <span className="text-[11px] font-medium text-gray-500 ml-1">Gene</span>
        <div className="relative" ref={geneSearchRef}>
          <input type="text" value={geneSearchInput}
            onChange={(e) => { setGeneSearchInput(e.target.value); setShowSuggestions(false) }}
            onFocus={() => { if (geneSuggestions.length) setShowSuggestions(true) }}
            onKeyDown={(e) => { if (e.key === 'Enter' && geneSearchInput.trim()) { setSelectedGene(geneSearchInput.trim()); setGeneSearchInput(''); setShowSuggestions(false) } }}
            onBlur={() => { if (geneSearchInput.trim()) { setSelectedGene(geneSearchInput.trim()); setGeneSearchInput('') } }}
            placeholder={selectedGene || 'Search gene...'}
            className="text-xs border border-gray-200 rounded px-2 py-0.5 bg-white text-gray-700 outline-none focus:border-blue-400 w-24" />
          {showSuggestions && geneSuggestions.length > 0 && (
            <div className="absolute top-full left-0 mt-0.5 bg-white border border-gray-200 rounded-lg shadow-lg z-20 max-h-[200px] overflow-y-auto min-w-[140px]">
              {geneSuggestions.map(g => (
                <button key={g} onClick={() => { setSelectedGene(g); setGeneSearchInput(''); setShowSuggestions(false) }}
                  className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-blue-50 text-gray-700 border-b border-gray-50 last:border-0">{g}</button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="min-h-0 border-b border-gray-200 overflow-hidden flex flex-col" style={{ height: heights[0] }}>
        <PlotImage realPath={realPath} gene={selectedGene} conditionCol={conditionCol} metric={metric} plotType="barplot" palette={palette} />
      </div>

      <DragHandle onDrag={useCallback((d: number) => adjustHeight(0, d), [adjustHeight])} />

      <div className="bg-white overflow-hidden flex flex-col" style={{ height: heights[1] }}>
        <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-3 pt-1 pb-0.5 shrink-0">Aggregate Detail Table</div>
        <div className="flex-1 min-h-0 overflow-auto">
          <AggregateDetailTable realPath={realPath} gene={selectedGene} conditionCol={conditionCol} />
        </div>
      </div>

      <DragHandle onDrag={useCallback((d: number) => adjustHeight(1, d), [adjustHeight])} />

      <div className="bg-white overflow-hidden flex flex-col" style={{ height: sec3Height }}>
        <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-3 pt-1 pb-0.5 shrink-0">Fisher Exact Test</div>
        <div className="flex-1 min-h-0 overflow-auto">
          <FisherTable realPath={realPath} gene={selectedGene} conditionCol={conditionCol} />
        </div>
      </div>
    </div>
  )
}
