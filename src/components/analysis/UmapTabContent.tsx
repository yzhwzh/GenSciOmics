import { useState, useEffect, useCallback, useRef } from 'react'
import { Loader2, XCircle } from 'lucide-react'
import AsyncCreatableSelect from 'react-select/async-creatable'
import { fetchUmapRatioPlots, fetchMarkerDotplot, searchGenes } from '../../api/analysis'
import FilterDropdown from '../FilterDropdown'
import UmapPlot from './UmapPlot'
import ZoomableImage from './ZoomableImage'
import DragHandle from './DragHandle'
import { PALETTE_OPTIONS } from '../../api/types'
import type { UmapData, UmapRatioPlots, MarkerDotplotResult } from '../../api/types'
import type { StylesConfig } from 'react-select'

interface Option {
  value: string
  label: string
}

// ── Tailwind-styled react-select theme (reused from RawDataDownload) ──
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

export default function UmapTabContent({
  realPath, umapData, umapLoading, colorBy, onColorByChange, geneName, onGeneNameChange, geneName2, onGeneName2Change, palette, onPaletteChange,
  markerMajor,
}: {
  realPath: string; umapData: UmapData | null; umapLoading: boolean; colorBy: string; onColorByChange: (v: string) => void; geneName: string; onGeneNameChange: (v: string) => void; geneName2: string; onGeneName2Change: (v: string) => void; palette: string; onPaletteChange: (v: string) => void
  markerMajor?: Record<string, string[]> | null
}) {
  const [plotData, setPlotData] = useState<UmapRatioPlots | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const bottomLeftRef = useRef<HTMLDivElement>(null)

  // Outer split: bottom-left vs bottom-right (vertical drag)
  const [splitPct, setSplitPct] = useState(50)
  // Inner split: boxplot vs table inside bottom-left (horizontal drag)
  const [innerSplitPct, setInnerSplitPct] = useState(50)

  // Right panel tab: 'ratio' | 'count'
  const [rightTab, setRightTab] = useState<'ratio' | 'count'>('ratio')

  // Dotplot state (visible for ALL datasets)
  const [dotplotData, setDotplotData] = useState<MarkerDotplotResult | null>(null)
  const [dotplotLoading, setDotplotLoading] = useState(false)
  const [dotplotError, setDotplotError] = useState<string | null>(null)
  const [dotplotGroupFilter, setDotplotGroupFilter] = useState('')
  const [targetGenes, setTargetGenes] = useState<Option[]>([])

  useEffect(() => {
    if (!realPath) return
    let cancelled = false
    fetchUmapRatioPlots(realPath, 'Group', palette)
      .then(d => {
        if (cancelled) return
        if ('error' in d) { setError(String((d as any).error)); setPlotData(null) }
        else { setPlotData(d) }
      }).catch(e => { if (!cancelled) { setError(e.message); setPlotData(null) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [realPath, palette])

  useEffect(() => {
    if (!realPath) return
    let cancelled = false
    const genesStr = targetGenes.map(g => g.value).join(',')
    fetchMarkerDotplot(realPath, palette, dotplotGroupFilter, genesStr)
      .then(d => {
        if (cancelled) return
        if (d.error) { setDotplotError(d.error); setDotplotData(null) }
        else { setDotplotData(d) }
      }).catch(e => { if (!cancelled) { setDotplotError(e.message); setDotplotData(null) } })
      .finally(() => { if (!cancelled) setDotplotLoading(false) })
    return () => { cancelled = true }
  }, [realPath, palette, dotplotGroupFilter, targetGenes])

  // Async gene search for Target input
  const loadGeneOptions = useCallback(async (input: string): Promise<Option[]> => {
    if (!input || input.length < 1) return []
    try {
      const results = await searchGenes(realPath, input)
      return results.slice(0, 30).map(g => ({ value: g, label: g }))
    } catch {
      return []
    }
  }, [realPath])

  // Outer drag handle: vertical split between bottom-left and bottom-right
  const handleSplitDrag = useCallback((delta: number) => {
    const container = bottomRef.current
    if (!container) return
    const containerW = container.clientWidth
    const deltaPct = (delta / containerW) * 100
    setSplitPct(prev => Math.max(20, Math.min(80, prev + deltaPct)))
  }, [])

  // Inner drag handle: horizontal split between boxplot and table inside bottom-left
  const handleInnerSplitDrag = useCallback((delta: number) => {
    const container = bottomLeftRef.current
    if (!container) return
    const containerH = container.clientHeight
    const deltaPct = (delta / containerH) * 100
    setInnerSplitPct(prev => Math.max(20, Math.min(80, prev + deltaPct)))
  }, [])

  const pairwise = plotData?.pairwise
  const [pairFilter, setPairFilter] = useState<Set<string> | undefined>(undefined)

  const handlePairToggle = (value: string) => {
    setPairFilter(prev => {
      const next = new Set(prev ?? [])
      if (next.has(value)) next.delete(value)
      else next.add(value)
      return next.size > 0 ? next : undefined
    })
  }

  const clearPairFilter = () => setPairFilter(undefined)

  const filteredPairs = pairwise && pairFilter && pairFilter.size > 0
    ? pairwise.pairs.filter(p => pairFilter.has(p))
    : pairwise?.pairs ?? []

  const filteredMatrix = pairwise && pairFilter && pairFilter.size > 0
    ? pairwise.pairs
        .map((p, i) => ({ pair: p, row: (pairwise as any).matrix[i] }))
        .filter(({ pair }) => pairFilter.has(pair))
        .map(({ row }) => row)
    : (pairwise as any)?.matrix ?? []

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-1 border-b border-border-light shrink-0">
        <span className="text-[11px] font-medium text-text-muted">Palette</span>
        <select value={palette} onChange={(e) => onPaletteChange(e.target.value)}
          disabled={colorBy === 'Gene'}
          className="text-xs border border-border-light rounded px-2 py-0.5 bg-surface text-text-secondary outline-none focus:border-blue-400 disabled:opacity-40 disabled:cursor-not-allowed">
          {PALETTE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      <div className="flex-1 flex flex-col gap-2 p-2 min-h-0 overflow-auto">

        {/* Top Row: UMAP (left) + Tab Panel (right) */}
        <div className="grid grid-cols-2 gap-2 min-h-0" style={{ flex: '0 0 52%' }}>
          {/* Top-Left: UMAP */}
          <div className="bg-surface rounded-lg border border-border-light overflow-hidden min-h-0 flex flex-col">
            <div className="text-[10px] font-semibold text-text-muted uppercase tracking-wider px-2 pt-1 pb-0 shrink-0">UMAP</div>
            <div className="flex-1 min-h-0"><UmapPlot data={umapData} loading={umapLoading} colorBy={colorBy} onColorByChange={onColorByChange} geneName={geneName} onGeneNameChange={onGeneNameChange} geneName2={geneName2} onGeneName2Change={onGeneName2Change} /></div>
          </div>

          {/* Top-Right: Tab-switchable panel (2 tabs: ratio / count) */}
          <div className="bg-surface rounded-lg border border-border-light overflow-hidden min-h-0 flex flex-col">
            <div className="flex items-center gap-0 shrink-0 border-b border-border-light">
              <button
                onClick={() => setRightTab('ratio')}
                className={`flex-1 text-[10px] font-semibold uppercase tracking-wider py-1.5 text-center cursor-pointer transition-colors ${
                  rightTab === 'ratio'
                    ? 'text-brand border-b-2 border-brand-gold bg-surface-raised'
                    : 'text-text-muted hover:text-text-secondary border-b-2 border-transparent'
                }`}
              >Cell Type Ratio per Sample</button>
              <button
                onClick={() => setRightTab('count')}
                className={`flex-1 text-[10px] font-semibold uppercase tracking-wider py-1.5 text-center cursor-pointer transition-colors ${
                  rightTab === 'count'
                    ? 'text-brand border-b-2 border-brand-gold bg-surface-raised'
                    : 'text-text-muted hover:text-text-secondary border-b-2 border-transparent'
                }`}
              >Cells per Sample</button>
            </div>
            <div className="flex-1 min-h-0 flex items-center justify-center">
              {rightTab === 'ratio' && (
                <>
                  {loading && <Loader2 className="w-5 h-5 text-brand animate-spin" />}
                  {error && <span className="text-xs text-text-muted">{error}</span>}
                  {plotData?.stacked_bar && (
                    <ZoomableImage src={`data:image/png;base64,${plotData.stacked_bar}`} alt="Cell ratio per sample" className="w-full h-full object-contain" />
                  )}
                  {!loading && !error && !plotData?.stacked_bar && <span className="text-xs text-text-muted">No data</span>}
                </>
              )}
              {rightTab === 'count' && (
                <>
                  {loading && <Loader2 className="w-5 h-5 text-brand animate-spin" />}
                  {error && <span className="text-xs text-text-muted">{error}</span>}
                  {plotData?.cell_count_bar && (
                    <ZoomableImage src={`data:image/png;base64,${plotData.cell_count_bar}`} alt="Cell Count" className="w-full h-full object-contain" />
                  )}
                  {!loading && !error && !plotData?.cell_count_bar && <span className="text-xs text-text-muted">No data</span>}
                </>
              )}
            </div>
            {rightTab === 'count' && plotData?.low_cell_pct != null && (
              <div className="shrink-0 text-[10px] text-text-muted text-center py-0.5 border-t border-border-light">
                Sample × CellType ≤10 cells: <span className="font-semibold text-red-600">{plotData.low_cell_pct}%</span>
              </div>
            )}
          </div>
        </div>

        {/* Bottom Row: left-right split — Boxplot+Table (left) | Dotplot (right) */}
        <div ref={bottomRef} className="flex flex-1 min-h-0 gap-0">
          {/* Bottom-Left: Boxplot (top) + DragHandle (horizontal) + Pairwise Table (bottom) */}
          <div className="bg-surface rounded-lg border border-border-light overflow-hidden flex flex-col min-h-0" style={{ width: `${splitPct}%` }}>
            <div className="px-2 pt-1 pb-0 shrink-0">
              <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">Cell Type Ratio by Group</span>
            </div>
            <div ref={bottomLeftRef} className="flex-1 flex flex-col min-h-0">
              {/* Boxplot */}
              <div className="min-h-0 flex items-center justify-center overflow-hidden" style={{ height: `${innerSplitPct}%` }}>
                {loading && <Loader2 className="w-5 h-5 text-brand animate-spin" />}
                {error && <span className="text-xs text-text-muted">{error}</span>}
                {plotData?.ratio_boxplot && <ZoomableImage src={`data:image/png;base64,${plotData.ratio_boxplot}`} alt="Boxplot" className="w-full h-full object-contain" />}
                {!loading && !error && !plotData?.ratio_boxplot && <span className="text-xs text-text-muted">No data</span>}
              </div>
              {/* Horizontal drag handle */}
              <DragHandle onDrag={handleInnerSplitDrag} orientation="horizontal" />
              {/* Pairwise table */}
              {pairwise && pairwise.pairs.length > 0 ? (
                <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto">
                  <div className="flex items-center gap-1 px-1 pt-0.5 min-h-[16px]">
                    {pairFilter && (
                      <button onClick={clearPairFilter} className="inline-flex items-center gap-0.5 text-[9px] text-brand hover:text-brand-dark">
                        <XCircle className="w-2.5 h-2.5" />
                        Clear
                      </button>
                    )}
                  </div>
                  <table className="w-full text-[9px]">
                    <thead>
                      <tr className="bg-surface-raised text-text-muted sticky top-0 z-10">
                        <th className="px-1.5 py-0.5 text-left font-medium whitespace-nowrap">
                          <FilterDropdown
                            label="Pair"
                            values={pairwise.pairs}
                            selectedValues={pairFilter}
                            onToggle={handlePairToggle}
                            onClear={clearPairFilter}
                            isActive={!!pairFilter}
                          />
                        </th>
                        {pairwise.cell_types.slice(0, 20).map(ct => (
                          <th key={ct} className="px-1.5 py-0.5 text-right font-medium whitespace-nowrap" title={ct}>{ct.length > 8 ? ct.slice(0, 8) + '...' : ct}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPairs.map((pair, pi) => (
                        <tr key={pair} className="border-t border-border-light hover:bg-surface-raised even:bg-surface-muted/30">
                          <td className="px-1.5 py-0.5 text-left font-medium text-text-secondary whitespace-nowrap">{pair.replace('_vs_', ' vs ')}</td>
                          {filteredMatrix[pi]?.slice(0, 20).map((pVal: any, ci: number) => {
                            const sig = pVal !== null && pVal <= 0.05
                            const valStr = pVal === null ? '-' : pVal < 0.001 ? '<0.001' : pVal.toFixed(4)
                            return (
                              <td key={ci} className={`px-1.5 py-0.5 text-right font-mono ${sig ? 'text-red-600 font-bold bg-error-bg' : 'text-text-secondary'}`}>
                                {valStr}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {pairwise.cell_types.length > 20 && (
                    <div className="text-[9px] text-text-muted text-center py-0.5">Showing 20 of {pairwise.cell_types.length} cell types</div>
                  )}
                </div>
              ) : (
                <div className="flex-1 flex items-center justify-center text-xs text-text-muted">No pairwise data</div>
              )}
            </div>
          </div>

          {/* Vertical drag handle between left and right */}
          <DragHandle onDrag={handleSplitDrag} orientation="vertical" />

          {/* Bottom-Right: Dotplot panel (visible for ALL datasets) */}
          <div className="bg-surface rounded-lg border border-border-light overflow-hidden flex flex-col min-h-0" style={{ width: `${100 - splitPct}%` }}>
            {/* Header + controls */}
            <div className="flex items-center gap-2 px-2 py-1 shrink-0 border-b border-border-light">
              <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">Marker Gene Dotplot</span>
              {/* Target gene input (multi-select chips) */}
              <div className="flex items-center gap-1 min-w-0">
                <span className="text-[10px] text-text-muted shrink-0">Target:</span>
                <AsyncCreatableSelect
                  isMulti
                  cacheOptions
                  defaultOptions={false}
                  loadOptions={loadGeneOptions}
                  onChange={(v) => setTargetGenes(v as Option[])}
                  value={targetGenes}
                  placeholder="Search genes..."
                  noOptionsMessage={({ inputValue }) => inputValue ? 'No genes found' : 'Type to search'}
                  styles={selectStyles}
                  className="flex-1 min-w-0"
                />
              </div>
              {/* Group filter */}
              {dotplotData?.groups && dotplotData.groups.length > 0 && (
                <div className="ml-auto flex items-center gap-1">
                  <span className="text-[10px] text-text-muted">Group:</span>
                  <select
                    value={dotplotGroupFilter}
                    onChange={(e) => setDotplotGroupFilter(e.target.value)}
                    className="text-xs border border-border-light rounded px-1.5 py-0.5 bg-surface text-text-secondary outline-none focus:border-blue-400"
                  >
                    <option value="">All</option>
                    {dotplotData.groups.map(g => <option key={g} value={g}>{g}</option>)}
                  </select>
                </div>
              )}
            </div>
            {/* Dotplot image */}
            <div className="flex-1 min-h-0 flex items-center justify-center">
              {dotplotLoading && <Loader2 className="w-5 h-5 text-brand animate-spin" />}
              {dotplotError && <span className="text-xs text-text-muted px-2">{dotplotError}</span>}
              {dotplotData?.image && (
                <ZoomableImage src={`data:image/png;base64,${dotplotData.image}`} alt="Marker dotplot" className="w-full h-full object-contain" />
              )}
              {!dotplotLoading && !dotplotError && !dotplotData?.image && <span className="text-xs text-text-muted">No data</span>}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
