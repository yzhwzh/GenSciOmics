import { useState, useEffect, useRef } from 'react'
import { searchGenes, fetchCompositionPlot } from '../../api/analysis'
import { PALETTE_OPTIONS } from '../../api/types'
import PlotImage from './PlotImage'
import AggregateDetailTable from './AggregateDetailTable'
import FisherTable from './FisherTable'
import ZoomableImage from './ZoomableImage'

export default function ExpressionChartContainer({ realPath }: { realPath: string }) {
  const geneSearchRef = useRef<HTMLDivElement>(null)
  const [metric, setMetric] = useState<'mean_expression' | 'expression_pct'>('expression_pct')
  const [selectedGene, setSelectedGene] = useState(() => {
    try { return sessionStorage.getItem('gensci_agg_gene') ?? 'FAP' } catch { return 'FAP' }
  })
  const [geneSearchInput, setGeneSearchInput] = useState('')
  const [geneSuggestions, setGeneSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [conditionCol, setConditionCol] = useState('Group')
  const [palette, setPalette] = useState('default')
  const [tableTab, setTableTab] = useState<'aggregate' | 'fisher'>('aggregate')
  const [compositionImg, setCompositionImg] = useState('')
  const [compLoading, setCompLoading] = useState(false)
  const [selectedGene2, setSelectedGene2] = useState('')
  const [gene2Input, setGene2Input] = useState('')
  const [gene2Suggestions, setGene2Suggestions] = useState<string[]>([])
  const [showGene2Suggestions, setShowGene2Suggestions] = useState(false)
  const gene2Ref = useRef<HTMLDivElement>(null)

  useEffect(() => { try { sessionStorage.setItem('gensci_agg_gene', selectedGene) } catch { /* ignore */ } }, [selectedGene])

  // Fetch cell type composition plot when metric is pct
  useEffect(() => {
    if (!realPath || metric !== 'expression_pct' || !selectedGene) { setCompositionImg(''); return }
    let cancelled = false
    setCompLoading(true)
    fetchCompositionPlot(realPath, selectedGene, palette, selectedGene2)
      .then(d => { if (!cancelled) { setCompositionImg(d.image ?? ''); setCompLoading(false) } })
      .catch(() => { if (!cancelled) { setCompositionImg(''); setCompLoading(false) } })
    return () => { cancelled = true }
  }, [realPath, metric, selectedGene, selectedGene2, palette])

  // Gene2 search
  useEffect(() => {
    if (!realPath || gene2Input.length < 1) { setGene2Suggestions([]); return }
    const timer = setTimeout(() => {
      searchGenes(realPath, gene2Input).then(genes => { setGene2Suggestions(genes); setShowGene2Suggestions(true) }).catch(() => setGene2Suggestions([]))
    }, 200)
    return () => clearTimeout(timer)
  }, [realPath, gene2Input])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (gene2Ref.current && !gene2Ref.current.contains(e.target as Node)) setShowGene2Suggestions(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (!realPath || geneSearchInput.length < 1) { setGeneSuggestions([]); return }
    const timer = setTimeout(() => {
      searchGenes(realPath, geneSearchInput).then(genes => { setGeneSuggestions(genes); setShowSuggestions(true) }).catch(() => setGeneSuggestions([]))
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
    <div className="h-full flex">
      {/* Left Control Panel */}
      <div className="w-[172px] shrink-0 bg-surface-raised border-r border-border-light p-3 flex flex-col gap-3.5 overflow-y-auto">
        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Gene</label>
          <div className="relative" ref={geneSearchRef}>
            <input type="text" value={geneSearchInput}
              onChange={(e) => { setGeneSearchInput(e.target.value); setShowSuggestions(false) }}
              onFocus={() => { if (geneSuggestions.length) setShowSuggestions(true) }}
              onKeyDown={(e) => { if (e.key === 'Enter' && geneSearchInput.trim()) { setSelectedGene(geneSearchInput.trim()); setGeneSearchInput(''); setShowSuggestions(false) } }}
              onBlur={() => { if (geneSearchInput.trim()) { setSelectedGene(geneSearchInput.trim()); setGeneSearchInput('') } }}
              placeholder={selectedGene || 'Search...'}
              className="w-full text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-primary outline-none focus:border-brand font-medium" />
            {showSuggestions && geneSuggestions.length > 0 && (
              <div className="absolute top-full left-0 mt-0.5 bg-surface border border-border-light rounded-md shadow-overlay z-20 max-h-[180px] overflow-y-auto w-full">
                {geneSuggestions.map(g => (
                  <button key={g} onClick={() => { setSelectedGene(g); setGeneSearchInput(''); setShowSuggestions(false) }}
                    className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-surface-muted text-text-secondary border-b border-border-light last:border-0">{g}</button>
                ))}
              </div>
            )}
          </div>
        </div>

        {metric === 'expression_pct' && (
        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Gene 2 <span className="font-normal text-text-muted">(共表达)</span></label>
          <div className="relative" ref={gene2Ref}>
            <input type="text" value={gene2Input}
              onChange={(e) => { setGene2Input(e.target.value); setShowGene2Suggestions(false) }}
              onFocus={() => { if (gene2Suggestions.length) setShowGene2Suggestions(true) }}
              onKeyDown={(e) => { if (e.key === 'Enter' && gene2Input.trim()) { setSelectedGene2(gene2Input.trim()); setGene2Input(''); setShowGene2Suggestions(false) } }}
              onBlur={() => { if (gene2Input.trim()) { setSelectedGene2(gene2Input.trim()); setGene2Input('') } }}
              placeholder={selectedGene2 || 'Optional...'}
              className="w-full text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-primary outline-none focus:border-brand" />
            {showGene2Suggestions && gene2Suggestions.length > 0 && (
              <div className="absolute top-full left-0 mt-0.5 bg-surface border border-border-light rounded-md shadow-overlay z-20 max-h-[180px] overflow-y-auto w-full">
                {gene2Suggestions.map(g => (
                  <button key={g} onClick={() => { setSelectedGene2(g); setGene2Input(''); setShowGene2Suggestions(false) }}
                    className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-surface-muted text-text-secondary border-b border-border-light last:border-0">{g}</button>
                ))}
              </div>
            )}
          </div>
          {selectedGene2 && (
            <button onClick={() => setSelectedGene2('')}
              className="text-[10px] text-text-muted hover:text-error mt-1">✕ clear</button>
          )}
        </div>
        )}

        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Condition</label>
          <select value={conditionCol} onChange={(e) => setConditionCol(e.target.value)}
            className="w-full text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-secondary outline-none focus:border-brand">
            <option value="None">None</option>
            <option value="Group">Group</option>
          </select>
        </div>

        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Metric</label>
          <div className="flex bg-surface-muted rounded-sm p-0.5 text-xs">
            <button onClick={() => setMetric('mean_expression')}
              className={`flex-1 text-center py-1 rounded-sm transition-colors ${metric === 'mean_expression' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>Mean</button>
            <button onClick={() => setMetric('expression_pct')}
              className={`flex-1 text-center py-1 rounded-sm transition-colors ${metric === 'expression_pct' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>%</button>
          </div>
        </div>

        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Palette</label>
          <select value={palette} onChange={(e) => setPalette(e.target.value)}
            className="w-full text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-secondary outline-none focus:border-brand">
            {PALETTE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>

      {/* Main: Chart + Table */}
      <div className="flex-1 flex flex-col min-w-0 p-2 gap-2">
        <div className="flex-1 flex gap-2 min-h-0">
          <div className="flex-1 bg-surface rounded-md shadow-card overflow-hidden min-w-0">
            <PlotImage realPath={realPath} gene={selectedGene} conditionCol={conditionCol} metric={metric} plotType="barplot" palette={palette} />
          </div>
          {(compositionImg || compLoading) && (
            <div className="w-[45%] bg-surface rounded-md shadow-card overflow-hidden shrink-0 flex items-center justify-center">
              {compLoading ? (
                <span className="text-xs text-text-muted">Loading composition...</span>
              ) : (
                <ZoomableImage src={compositionImg} alt="Cell type composition"
                  className="w-full h-full object-contain" />
              )}
            </div>
          )}
        </div>
        <div className="shrink-0 flex flex-col" style={{ flexBasis: '35%', minHeight: 140 }}>
          <div className="flex items-center gap-1 mb-1">
            <button onClick={() => setTableTab('aggregate')}
              className={`text-[11px] font-medium px-3 py-1 rounded-sm transition-colors ${tableTab === 'aggregate' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>Aggregate Table</button>
            <button onClick={() => setTableTab('fisher')}
              className={`text-[11px] font-medium px-3 py-1 rounded-sm transition-colors ${tableTab === 'fisher' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>Fisher Test</button>
            <span className="text-[10px] text-text-muted ml-auto">{metric === 'mean_expression' ? 'Mean' : '%'} Expression</span>
          </div>
          <div className="flex-1 bg-surface rounded-md shadow-card overflow-auto min-h-0">
            {tableTab === 'aggregate' ? (
              <AggregateDetailTable realPath={realPath} gene={selectedGene} conditionCol={conditionCol} palette={palette} />
            ) : (
              <FisherTable realPath={realPath} gene={selectedGene} conditionCol={conditionCol} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
