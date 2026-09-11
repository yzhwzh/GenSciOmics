import { useState, useEffect, useRef, useCallback } from 'react'
import { searchGenes } from '../../api/analysis'
import { resolveGeneChoice, unknownGeneMessage } from './geneInput'
import { useStoredGene, BOXPLOT_GENE_KEY } from './useStoredGene'
import { PALETTE_OPTIONS } from '../../api/types'
import PlotImage from './PlotImage'
import DetailTable from './DetailTable'
import MuTestTable from './MuTestTable'
import RawDataDownload from './RawDataDownload'
import ResolvedGeneNotice from './ResolvedGeneNotice'

export default function BoxPlotContainer({ realPath }: { realPath: string }) {
  const geneSearchRef = useRef<HTMLDivElement>(null)
  const [metric, setMetric] = useState<'expression_pct' | 'mean_expression'>('expression_pct')
  // Remembered per dataset: a gene chosen on another dataset is not restored
  // here. See useStoredGene.ts / BUG_LOG B34.
  const [selectedGene, setSelectedGene] = useStoredGene(BOXPLOT_GENE_KEY, realPath, 'FAP')
  // The gene the backend actually plotted for the request behind the chart on
  // screen, paired with what was asked for at the time.
  const [resolvedGene, setResolvedGene] = useState<{ asked: string; resolved: string } | null>(null)
  const handleResolvedGene = useCallback((resolved: string) => {
    setResolvedGene(resolved ? { asked: selectedGene, resolved } : null)
  }, [selectedGene])
  const [geneSearchInput, setGeneSearchInput] = useState('')
  const [geneSuggestions, setGeneSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  // Set when the typed text is not a gene in this dataset. The box has to say
  // so: silently committing the raw text is what let the backend resolve a
  // typed prefix into an unrelated gene. See geneInput.ts / BUG_LOG B28.
  const [geneInputError, setGeneInputError] = useState('')
  const [conditionCol, setConditionCol] = useState('Group')
  const [minCells, setMinCells] = useState(10)
  const [palette, setPalette] = useState('default')
  const [tableTab, setTableTab] = useState<'detail' | 'mutest'>('detail')

  // Asynchronous because the dropdown lags the typing by a 200ms debounce, so a
  // real gene typed in one go is often not listed yet — geneInput.ts asks the
  // server before refusing. resolveGeneChoice never rejects, so dropping the
  // promise at the two call sites below cannot surface as an unhandled rejection.
  const commitGene = useCallback(async (typed: string) => {
    const choice = await resolveGeneChoice(typed, geneSuggestions, (q) => searchGenes(realPath, q))
    if (choice.kind === 'commit') {
      setSelectedGene(choice.gene)
      setGeneSearchInput('')
      setGeneInputError('')
      setShowSuggestions(false)
    } else if (choice.kind === 'reject') {
      // Leave the text in the box and show what did match, so the reader can
      // pick one instead of getting a wrong gene that looks like a right one.
      setGeneSuggestions(choice.suggestions)
      setGeneInputError(choice.typed)
      setShowSuggestions(true)
    }
    // setSelectedGene is useStoredGene's `select`, a useCallback with an empty
    // dependency list, so its identity never changes and listing it here costs
    // no extra renders. The linter cannot see that through a custom hook, so
    // omitting it would leave a standing warning in which the next genuine
    // missing dependency would go unnoticed.
  }, [geneSuggestions, realPath, setSelectedGene])

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
      {/* Left Control Panel — 172px */}
      <div className="w-[172px] shrink-0 bg-surface-raised border-r border-border-light p-3 flex flex-col gap-3.5 overflow-y-auto">
        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Gene</label>
          <div className="relative" ref={geneSearchRef}>
            <input type="text" value={geneSearchInput}
              onChange={(e) => { setGeneSearchInput(e.target.value); setGeneInputError(''); setShowSuggestions(false) }}
              onFocus={() => { if (geneSuggestions.length) setShowSuggestions(true) }}
              onKeyDown={(e) => { if (e.key === 'Enter' && geneSearchInput.trim()) commitGene(geneSearchInput) }}
              onBlur={() => commitGene(geneSearchInput)}
              placeholder={selectedGene || 'Search...'}
              className="w-full text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-primary outline-none focus:border-brand font-medium" />
            {geneInputError && (
              <div className="text-[10px] text-error mt-1">{unknownGeneMessage(geneInputError)}</div>
            )}
            <ResolvedGeneNotice asked={selectedGene} resolution={resolvedGene} />
            {showSuggestions && geneSuggestions.length > 0 && (
              <div className="absolute top-full left-0 mt-0.5 bg-surface border border-border-light rounded-md shadow-overlay z-20 max-h-[180px] overflow-y-auto w-full">
                {geneSuggestions.map(g => (
                  <button key={g} onMouseDown={(e) => { e.preventDefault(); setSelectedGene(g); setGeneSearchInput(''); setShowSuggestions(false) }}
                    className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-surface-muted text-text-secondary border-b border-border-light last:border-0">{g}</button>
                ))}
              </div>
            )}
          </div>
        </div>

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

        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Min Cells</label>
          <input type="number" min={0} value={minCells} onChange={(e) => setMinCells(Math.max(0, parseInt(e.target.value) || 0))}
            className="w-full text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-secondary outline-none focus:border-brand" />
        </div>

        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Export</label>
          <RawDataDownload realPath={realPath} />
        </div>
      </div>

      {/* Main: Chart + Table */}
      <div className="flex-1 flex flex-col min-w-0 p-2 gap-2">
        <div className="flex-1 bg-surface rounded-md shadow-card overflow-hidden min-h-0">
          <PlotImage realPath={realPath} gene={selectedGene} conditionCol={conditionCol} metric={metric} plotType="boxplot" minCells={minCells} palette={palette} onResolvedGene={handleResolvedGene} />
        </div>
        <div className="shrink-0 flex flex-col" style={{ flexBasis: '35%', minHeight: 140 }}>
          <div className="flex items-center gap-1 mb-1">
            <button onClick={() => setTableTab('detail')}
              className={`text-[11px] font-medium px-3 py-1 rounded-sm transition-colors ${tableTab === 'detail' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>Detail Table</button>
            <button onClick={() => setTableTab('mutest')}
              className={`text-[11px] font-medium px-3 py-1 rounded-sm transition-colors ${tableTab === 'mutest' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>MU Test (P-values)</button>
            <span className="text-[10px] text-text-muted ml-auto">{metric === 'mean_expression' ? 'Mean' : '%'} Expression</span>
          </div>
          <div className="flex-1 bg-surface rounded-md shadow-card overflow-auto min-h-0">
            {tableTab === 'detail' ? (
              <DetailTable realPath={realPath} gene={selectedGene} conditionCol={conditionCol} />
            ) : (
              <MuTestTable realPath={realPath} gene={selectedGene} minCells={minCells} conditionCol={conditionCol} variant={metric === 'mean_expression' ? 'mean' : 'pct'} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
