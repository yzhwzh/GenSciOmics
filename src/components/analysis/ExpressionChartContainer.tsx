import { useState, useEffect, useRef, useCallback } from 'react'
import { searchGenes, fetchCompositionPlot } from '../../api/analysis'
import { PALETTE_OPTIONS } from '../../api/types'
import type { MergeOp } from '../../api/types'
import PlotImage from './PlotImage'
import AggregateDetailTable from './AggregateDetailTable'
import FisherTable from './FisherTable'
import MergeWarning from './MergeWarning'
import ZoomableImage from './ZoomableImage'
import AsyncCreatableSelect from 'react-select/async-creatable'
import type { StylesConfig } from 'react-select'
import { MERGE_OP_KEY, deriveG2Op, readStoredOp } from './mergeOp'
import { resolveGeneChoice, unknownGeneMessage } from './geneInput'

interface Option {
  value: string
  label: string
}

/** Stable identity for "no merge info" — a fresh literal per call would re-render the warning consumers pointlessly. */
const EMPTY_MERGE: { resolved: string[]; unresolved: string[] } = { resolved: [], unresolved: [] }

// Tailwind-styled react-select theme (same pattern as UmapTabContent / RawDataDownload)
const selectStyles: StylesConfig<Option, true> = {
  control: (base, { isFocused }) => ({
    ...base,
    borderColor: isFocused ? '#93c5fd' : '#e5e7eb',
    boxShadow: isFocused ? '0 0 0 1px #93c5fd' : 'none',
    '&:hover': { borderColor: '#93c5fd' },
    fontSize: '11px',
    minHeight: '28px',
    borderRadius: '6px',
    cursor: 'text',
  }),
  multiValue: (base) => ({
    ...base,
    backgroundColor: '#eff6ff',
    borderRadius: '4px',
    fontSize: '10px',
  }),
  multiValueLabel: (base) => ({
    ...base,
    color: '#1d4ed8',
    fontWeight: 500,
    padding: '1px 3px',
  }),
  multiValueRemove: (base) => ({
    ...base,
    color: '#93c5fd',
    '&:hover': { backgroundColor: '#dbeafe', color: '#2563eb' },
    borderRadius: '0 4px 4px 0',
  }),
  menu: (base) => ({
    ...base,
    fontSize: '11px',
    zIndex: 60,
  }),
  option: (base, { isFocused, isSelected }) => ({
    ...base,
    backgroundColor: isSelected ? '#2563eb' : isFocused ? '#eff6ff' : '#fff',
    color: isSelected ? '#fff' : '#374151',
    padding: '4px 8px',
    cursor: 'pointer',
  }),
  input: (base) => ({ ...base, fontSize: '11px' }),
  placeholder: (base) => ({ ...base, color: '#9ca3af', fontSize: '11px' }),
  noOptionsMessage: (base) => ({ ...base, fontSize: '11px', color: '#9ca3af' }),
}

export default function ExpressionChartContainer({ realPath }: { realPath: string }) {
  const geneSearchRef = useRef<HTMLDivElement>(null)
  const [metric, setMetric] = useState<'mean_expression' | 'expression_pct'>('expression_pct')
  const [selectedGene, setSelectedGene] = useState(() => {
    try { return sessionStorage.getItem('gensci_agg_gene') ?? 'FAP' } catch { return 'FAP' }
  })
  const [geneSearchInput, setGeneSearchInput] = useState('')
  const [geneSuggestions, setGeneSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  // Set when the typed text is not a gene in this dataset. The box has to say
  // so: silently committing the raw text is what let the backend resolve a
  // typed prefix into an unrelated gene. See geneInput.ts / BUG_LOG B28.
  const [geneInputError, setGeneInputError] = useState('')
  const [conditionCol, setConditionCol] = useState('Group')
  const [palette, setPalette] = useState('default')
  const [tableTab, setTableTab] = useState<'aggregate' | 'fisher'>('aggregate')
  const [compositionImg, setCompositionImg] = useState('')
  const [compLoading, setCompLoading] = useState(false)
  const [selectedGene2, setSelectedGene2] = useState('')
  const [gene2Input, setGene2Input] = useState('')
  const [gene2Suggestions, setGene2Suggestions] = useState<string[]>([])
  const [showGene2Suggestions, setShowGene2Suggestions] = useState(false)
  // Same guard as the Gene box above — see geneInput.ts / BUG_LOG B28.
  const [gene2InputError, setGene2InputError] = useState('')
  const [gene2Mode, setGene2Mode] = useState<'single' | 'merge'>('single')
  const [mergeGenes, setMergeGenes] = useState<Option[]>([])  // editable chips (staging — does NOT drive backend)
  const [mergeRun, setMergeRun] = useState<Option[]>([])      // applied members — the only thing that drives backend (Run)
  const [mergeLabel, setMergeLabel] = useState('')            // staging alias (editable)
  const [mergeLabelTouched, setMergeLabelTouched] = useState(false)
  const [mergeRunLabel, setMergeRunLabel] = useState('')      // applied alias — drives backend (Run)
  const [mergeOp, setMergeOp] = useState<MergeOp>(readStoredOp)      // staged 或/且 (does NOT drive backend)
  const [mergeRunOp, setMergeRunOp] = useState<MergeOp>(readStoredOp) // applied 或/且 — drives backend (Run)
  const [compMerge, setCompMerge] = useState(EMPTY_MERGE)
  const gene2Ref = useRef<HTMLDivElement>(null)

  // Downstream gene2: single Gene2 name, or the '|'-joined merge set (MergeGene).
  // Merge only commits on Run (mergeRun + mergeRunLabel + mergeRunOp); editing staging
  // must NOT hit backend.
  const mergeKey = (opts: Option[]) => opts.map(g => g.value).join('|')
  const defaultMergeLabel = mergeGenes.length > 0 ? `M${mergeGenes.length}` : ''   // recommended alias
  const stagedLabel = mergeLabelTouched ? mergeLabel.trim() : defaultMergeLabel
  const mergeDirty = mergeKey(mergeRun) !== mergeKey(mergeGenes)
    || stagedLabel !== mergeRunLabel
    || mergeOp !== mergeRunOp
  const g2 = gene2Mode === 'merge' ? mergeKey(mergeRun) : selectedGene2
  const g2Label = gene2Mode === 'merge' ? mergeRunLabel : ''   // user-named M, empty until a merge Run
  const g2Op = deriveG2Op(gene2Mode, mergeRun.length, mergeRunOp)
  // The operator toggle can dirty the panel on its own, so Run can't key off mergeDirty
  // alone. It must however stay clickable once the user empties the chips: committing an
  // empty set is the only way to drop an applied merge, and gating on mergeGenes.length
  // alone stranded exactly that state — no chips, no ✕, dead Run, merge still live.
  const canMergeRun = mergeDirty && (mergeGenes.length > 0 || mergeRun.length > 0)

  // Merge mode commits staged chips + alias + operator atomically on Run.
  const handleMergeRun = () => {
    const label = stagedLabel || defaultMergeLabel
    setMergeRun(mergeGenes.map(g => ({ ...g })))
    setMergeRunLabel(label)
    setMergeRunOp(mergeOp)
    if (!stagedLabel) { setMergeLabel(''); setMergeLabelTouched(false) }  // blank alias → reshow recommended default
  }
  // Sync the applied operator to whatever is staged: the Run button is gated on
  // mergeDirty (which the operator can now set on its own), so leaving it stale here
  // would strand a clickable Run button with no chips to run.
  const handleMergeClear = () => {
    setMergeGenes([]); setMergeRun([])
    setMergeLabel(''); setMergeLabelTouched(false); setMergeRunLabel('')
    setMergeRunOp(mergeOp)
  }

  // Async gene search for the MergeGene multi-select (mirrors UmapTabContent dotplot)
  const loadGeneOptions = useCallback(async (input: string): Promise<Option[]> => {
    if (!realPath || input.length < 1) return []
    try {
      const results = await searchGenes(realPath, input)
      return results.slice(0, 30).map(g => ({ value: g, label: g }))
    } catch {
      return []
    }
  }, [realPath])

  useEffect(() => { try { sessionStorage.setItem('gensci_agg_gene', selectedGene) } catch { /* ignore */ } }, [selectedGene])
  // Persist the APPLIED operator, mirroring gensci_agg_gene: switching 或/且 and then
  // reloading without pressing Run must not silently remember an uncommitted choice.
  useEffect(() => { try { sessionStorage.setItem(MERGE_OP_KEY, mergeRunOp) } catch { /* ignore */ } }, [mergeRunOp])

  // Fetch cell type composition plot when metric is pct
  useEffect(() => {
    if (!realPath || metric !== 'expression_pct' || !selectedGene) {
      // compLoading must be cleared too: the panel below renders on
      // (compositionImg || compLoading) and sits OUTSIDE the metric gate, so an
      // abandoned in-flight request would otherwise pin it on "Loading..." forever
      // (the .then below bails out via `cancelled` and never clears it).
      setCompositionImg(''); setCompMerge(EMPTY_MERGE); setCompLoading(false); return
    }
    let cancelled = false
    setCompLoading(true)
    fetchCompositionPlot(realPath, selectedGene, palette, g2, g2Label, g2Op)
      .then(d => {
        if (cancelled) return
        setCompositionImg(d.image ?? '')
        setCompMerge({ resolved: d.gene2_resolved ?? [], unresolved: d.gene2_unresolved ?? [] })
        setCompLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setCompositionImg(''); setCompMerge(EMPTY_MERGE); setCompLoading(false)
      })
    return () => { cancelled = true }
  }, [realPath, metric, selectedGene, g2, g2Label, g2Op, palette])

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

  // Asynchronous because the dropdown lags the typing by a 200ms debounce, so a
  // real gene typed in one go is often not listed yet — geneInput.ts asks the
  // server before refusing. resolveGeneChoice never rejects, so dropping the
  // promise at the call sites below cannot surface as an unhandled rejection.
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
  }, [geneSuggestions, realPath])

  const commitGene2 = useCallback(async (typed: string) => {
    const choice = await resolveGeneChoice(typed, gene2Suggestions, (q) => searchGenes(realPath, q))
    if (choice.kind === 'commit') {
      setSelectedGene2(choice.gene)
      setGene2Input('')
      setGene2InputError('')
      setShowGene2Suggestions(false)
    } else if (choice.kind === 'reject') {
      setGene2Suggestions(choice.suggestions)
      setGene2InputError(choice.typed)
      setShowGene2Suggestions(true)
    }
  }, [gene2Suggestions, realPath])

  return (
    <div className="h-full flex">
      {/* Left Control Panel */}
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

        {metric === 'expression_pct' && (
        <div>
          <div className="flex items-center justify-between gap-1 mb-1">
            <label className="text-[10px] font-semibold text-text-muted">共表达</label>
            <div className="flex bg-surface-muted rounded-sm p-px text-[9px] leading-none shrink-0">
              <button onClick={() => setGene2Mode('single')}
                className={`px-1.5 py-[3px] rounded-sm transition-colors ${gene2Mode === 'single' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>GENE2</button>
              <button onClick={() => setGene2Mode('merge')}
                className={`px-1.5 py-[3px] rounded-sm transition-colors ${gene2Mode === 'merge' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>MERGE</button>
            </div>
          </div>
          {gene2Mode === 'single' ? (
            <>
              <div className="relative" ref={gene2Ref}>
                <input type="text" value={gene2Input}
                  onChange={(e) => { setGene2Input(e.target.value); setGene2InputError(''); setShowGene2Suggestions(false) }}
                  onFocus={() => { if (gene2Suggestions.length) setShowGene2Suggestions(true) }}
                  onKeyDown={(e) => { if (e.key === 'Enter' && gene2Input.trim()) commitGene2(gene2Input) }}
                  onBlur={() => commitGene2(gene2Input)}
                  placeholder={selectedGene2 || 'Optional...'}
                  className="w-full text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-primary outline-none focus:border-brand" />
                {gene2InputError && (
                  <div className="text-[10px] text-error mt-1">{unknownGeneMessage(gene2InputError)}</div>
                )}
                {showGene2Suggestions && gene2Suggestions.length > 0 && (
                  <div className="absolute top-full left-0 mt-0.5 bg-surface border border-border-light rounded-md shadow-overlay z-20 max-h-[180px] overflow-y-auto w-full">
                    {gene2Suggestions.map(g => (
                      <button key={g} onMouseDown={(e) => { e.preventDefault(); setSelectedGene2(g); setGene2Input(''); setShowGene2Suggestions(false) }}
                        className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-surface-muted text-text-secondary border-b border-border-light last:border-0">{g}</button>
                    ))}
                  </div>
                )}
              </div>
              {selectedGene2 && (
                <button onClick={() => setSelectedGene2('')}
                  className="text-[10px] text-text-muted hover:text-error mt-1">✕ clear</button>
              )}
            </>
          ) : (
            <>
              <AsyncCreatableSelect
                isMulti
                cacheOptions
                // Merge members must be real genes. Search (routes.py:279) and the backend
                // resolver (utils.py:124) share one predicate, so anything mergeable is
                // listable — Create adds no capability, and a hand-typed token that merely
                // contains a real name (e.g. COL1) would be silently resolved to whichever
                // gene matches first and reported as resolved, suppressing the warning.
                // See B28.
                isValidNewOption={() => false}
                loadOptions={loadGeneOptions}
                onChange={(v) => {
                  const next = (v ?? []) as Option[]
                  setMergeGenes(next)
                  if (!next.length) { setMergeLabel(''); setMergeLabelTouched(false) }  // no chips → drop stale alias
                }}
                value={mergeGenes}
                placeholder="Search genes..."
                noOptionsMessage={({ inputValue }) => inputValue ? 'No genes found' : 'Type to search'}
                styles={selectStyles}
              />
              <input
                type="text"
                value={stagedLabel}
                onChange={(e) => { setMergeLabel(e.target.value); setMergeLabelTouched(true) }}
                disabled={!mergeGenes.length}
                maxLength={40}
                placeholder={mergeGenes.length ? '合并基因别名 (M#)' : '合并基因别名'}
                title={mergeGenes.length ? '合并基因显示名，Run 后生效' : '先选择要合并的基因'}
                className="w-full mt-1 text-[10px] border border-border-light rounded-sm px-1.5 py-[3px] bg-surface text-text-primary outline-none focus:border-brand disabled:opacity-50"
              />
              <div className="flex items-center justify-between gap-1 mt-1">
                <span id="merge-op-label" className="text-[10px] text-text-muted">合并规则</span>
                <div role="group" aria-labelledby="merge-op-label"
                  className="flex bg-surface-muted rounded-sm p-px text-[9px] leading-none shrink-0">
                  {/* aria-pressed carries the selection (it is otherwise colour-only) and
                      aria-label carries the semantics, which `title` alone can't reach on touch. */}
                  <button onClick={() => setMergeOp('or')}
                    aria-pressed={mergeOp === 'or'}
                    aria-label="或：任一成员基因表达即为阳性（并集）"
                    title="任一成员基因表达即为阳性（并集）"
                    className={`px-1.5 py-[3px] rounded-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${mergeOp === 'or' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>或</button>
                  <button onClick={() => setMergeOp('and')}
                    aria-pressed={mergeOp === 'and'}
                    aria-label="且：所有成员基因都表达才为阳性（交集）"
                    title="所有成员基因都表达才为阳性（交集）"
                    className={`px-1.5 py-[3px] rounded-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${mergeOp === 'and' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>且</button>
                </div>
              </div>
              <div className="flex items-center gap-1.5 mt-1">
                {(mergeGenes.length > 0 || mergeRun.length > 0) && (
                  <button onClick={handleMergeClear}
                    className="text-[10px] text-text-muted hover:text-error">✕ clear</button>
                )}
                <span className="ml-auto flex items-center">
                  {canMergeRun && (
                    <span className="text-[9px] text-text-muted mr-1.5">(改动未应用)</span>
                  )}
                  <button
                    onClick={handleMergeRun}
                    disabled={!canMergeRun}
                    className={`px-2 py-[3px] rounded-sm text-[9px] leading-none font-semibold transition-colors ${
                      canMergeRun
                        ? 'bg-brand text-white shadow-card hover:opacity-90'
                        : 'bg-surface-muted text-text-muted cursor-default'}`}>Run</button>
                </span>
              </div>
            </>
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
            <div className="w-[45%] bg-surface rounded-md shadow-card overflow-hidden shrink-0 flex flex-col">
              <MergeWarning unresolved={compMerge.unresolved} resolved={compMerge.resolved} op={g2Op} />
              <div className="flex-1 flex items-center justify-center min-h-0">
                {compLoading ? (
                  <span className="text-xs text-text-muted">Loading composition...</span>
                ) : (
                  <ZoomableImage src={compositionImg} alt="Cell type composition"
                    className="w-full h-full object-contain" />
                )}
              </div>
            </div>
          )}
        </div>
        <div className="shrink-0 flex flex-col" style={{ flexBasis: '35%', minHeight: 140 }}>
          <div className="flex items-center gap-1 mb-1">
            <button onClick={() => setTableTab('aggregate')}
              className={`text-[11px] font-medium px-3 py-1 rounded-sm transition-colors ${tableTab === 'aggregate' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>Aggregate Table</button>
            <button onClick={() => setTableTab('fisher')}
              className={`text-[11px] font-medium px-3 py-1 rounded-sm transition-colors ${tableTab === 'fisher' ? 'bg-surface text-brand font-semibold shadow-card' : 'text-text-muted hover:text-text-secondary'}`}>Fisher Test</button>
            <span className="text-[10px] text-text-muted ml-auto flex items-center gap-1">
              {/* Always visible, unlike the 共表达 panel: in Mean mode the operator
                  toggle is hidden, so this is the only cue that the table's M is an
                  intersection rather than the historical union. */}
              {g2Op === 'and' && (
                <span title="合并基因 M 取成员交集（所有成员都表达）"
                  className="px-1 py-px rounded-sm text-[9px] font-semibold leading-none text-white bg-amber-500">AND</span>
              )}
              {metric === 'mean_expression' ? 'Mean' : '%'} Expression
            </span>
          </div>
          <div className="flex-1 bg-surface rounded-md shadow-card overflow-auto min-h-0">
            {tableTab === 'aggregate' ? (
              <AggregateDetailTable realPath={realPath} gene={selectedGene} conditionCol={conditionCol} palette={palette} gene2={g2} gene2Label={g2Label} gene2Op={g2Op} />
            ) : (
              <FisherTable realPath={realPath} gene={selectedGene} conditionCol={conditionCol} gene2={g2} gene2Label={g2Label} gene2Op={g2Op} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
