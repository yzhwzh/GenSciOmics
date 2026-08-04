import { useState, useEffect, useCallback, useRef } from 'react'
import { Loader2, XCircle } from 'lucide-react'
import { fetchUmapRatioPlots } from '../../api/analysis'
import FilterDropdown from '../FilterDropdown'
import UmapPlot from './UmapPlot'
import ZoomableImage from './ZoomableImage'
import DragHandle from './DragHandle'
import { PALETTE_OPTIONS } from '../../api/types'
import type { UmapData, UmapRatioPlots } from '../../api/types'

export default function UmapTabContent({
  realPath, umapData, umapLoading, colorBy, onColorByChange, geneName, onGeneNameChange, geneName2, onGeneName2Change, palette, onPaletteChange,
}: {
  realPath: string; umapData: UmapData | null; umapLoading: boolean; colorBy: string; onColorByChange: (v: string) => void; geneName: string; onGeneNameChange: (v: string) => void; geneName2: string; onGeneName2Change: (v: string) => void; palette: string; onPaletteChange: (v: string) => void
}) {
  const [plotData, setPlotData] = useState<UmapRatioPlots | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const boxplotRef = useRef<HTMLDivElement>(null)
  const [boxplotH, setBoxplotH] = useState(160)
  const [tableH, setTableH] = useState(100)

  const fetchPlots = useCallback(() => {
    if (!realPath) return
    setLoading(true); setError(null)
    fetchUmapRatioPlots(realPath, 'Group', palette)
      .then(d => {
        if ('error' in d) { setError(String((d as any).error)); setPlotData(null) }
        else { setPlotData(d) }
      }).catch(e => { setError(e.message); setPlotData(null) })
      .finally(() => setLoading(false))
  }, [realPath, palette])

  useEffect(() => { if (realPath) fetchPlots() }, [fetchPlots])

  useEffect(() => {
    const el = boxplotRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const total = el.clientHeight
      const titleH = 24
      const dragH = 5
      const used = titleH + boxplotH + dragH
      setTableH(Math.max(30, total - used))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [boxplotH])

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
      <div className="flex items-center gap-2 px-3 py-1 border-b border-gray-100 shrink-0">
        <span className="text-[11px] font-medium text-gray-500">Palette</span>
        <select value={palette} onChange={(e) => onPaletteChange(e.target.value)}
          disabled={colorBy === 'Gene'}
          className="text-xs border border-gray-200 rounded px-2 py-0.5 bg-white text-gray-700 outline-none focus:border-blue-400 disabled:opacity-40 disabled:cursor-not-allowed">
          {PALETTE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-2 p-2 min-h-0">
        {/* Top-Left: UMAP */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden min-h-0 flex flex-col h-full">
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-2 pt-1 pb-0 shrink-0">UMAP</div>
          <div className="flex-1 min-h-0"><UmapPlot data={umapData} loading={umapLoading} colorBy={colorBy} onColorByChange={onColorByChange} geneName={geneName} onGeneNameChange={onGeneNameChange} geneName2={geneName2} onGeneName2Change={onGeneName2Change} /></div>
        </div>

        {/* Top-Right: Cell Type Ratio per Sample */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden min-h-0 flex flex-col h-full">
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-2 pt-1 pb-0 shrink-0">Cell Type Ratio per Sample</div>
          <div className="flex-1 min-h-0 flex items-center justify-center">
            {loading && <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />}
            {error && <span className="text-xs text-gray-400">{error}</span>}
            {plotData?.stacked_bar && <ZoomableImage src={`data:image/png;base64,${plotData.stacked_bar}`} alt="Cell ratio per sample" className="w-full h-full object-contain" />}
            {!loading && !error && !plotData?.stacked_bar && <span className="text-xs text-gray-400">No data</span>}
          </div>
        </div>

        {/* Bottom-Left: Boxplot + Pairwise Stats */}
        <div ref={boxplotRef} className="bg-white rounded-lg border border-gray-200 overflow-hidden min-h-0 flex flex-col h-full">
          <div className="px-2 pt-1 pb-0 shrink-0">
            <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Cell Type Ratio by Group</span>
          </div>
          <div className="min-h-0 overflow-hidden" style={{ height: boxplotH }}>
            {loading && <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />}
            {error && <span className="text-xs text-gray-400">{error}</span>}
            {plotData?.ratio_boxplot && <ZoomableImage src={`data:image/png;base64,${plotData.ratio_boxplot}`} alt="Boxplot" className="w-full h-full object-contain" />}
            {!loading && !error && !plotData?.ratio_boxplot && <span className="text-xs text-gray-400">No data</span>}
          </div>
          <DragHandle onDrag={useCallback((d: number) => {
            setBoxplotH(prev => Math.max(60, prev + d))
          }, [])} />
          {pairwise && pairwise.pairs.length > 0 && (
            <div className="overflow-x-auto overflow-y-auto border-t border-gray-100" style={{ height: tableH }}>
              <div className="flex items-center gap-1 px-1 pt-0.5 min-h-[16px]">
                {pairFilter && (
                  <button onClick={clearPairFilter} className="inline-flex items-center gap-0.5 text-[9px] text-blue-600 hover:text-blue-800">
                    <XCircle className="w-2.5 h-2.5" />
                    Clear
                  </button>
                )}
              </div>
              <table className="w-full text-[9px]">
                <thead>
                  <tr className="bg-gray-50 text-gray-500 sticky top-0 z-10">
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
                    <tr key={pair} className="border-t border-gray-50 hover:bg-gray-50">
                      <td className="px-1.5 py-0.5 text-left font-medium text-gray-700 whitespace-nowrap">{pair.replace('_vs_', ' vs ')}</td>
                      {filteredMatrix[pi]?.slice(0, 20).map((pVal: any, ci: number) => {
                        const sig = pVal !== null && pVal <= 0.05
                        const valStr = pVal === null ? '-' : pVal < 0.001 ? '<0.001' : pVal.toFixed(4)
                        return (
                          <td key={ci} className={`px-1.5 py-0.5 text-right font-mono ${sig ? 'text-red-600 font-bold bg-red-50' : 'text-gray-600'}`}>
                            {valStr}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              {pairwise.cell_types.length > 20 && (
                <div className="text-[9px] text-gray-400 text-center py-0.5">Showing 20 of {pairwise.cell_types.length} cell types</div>
              )}
            </div>
          )}
        </div>

        {/* Bottom-Right: Cell Count Bar */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden min-h-0 flex flex-col h-full">
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-2 pt-1 pb-0 shrink-0">Cells per Sample</div>
          <div className="flex-1 min-h-0 flex items-center justify-center">
            {loading && <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />}
            {error && <span className="text-xs text-gray-400">{error}</span>}
            {plotData?.cell_count_bar && <ZoomableImage src={`data:image/png;base64,${plotData.cell_count_bar}`} alt="Cell Count" className="w-full h-full object-contain" />}
            {!loading && !error && !plotData?.cell_count_bar && <span className="text-xs text-gray-400">No data</span>}
          </div>
          {plotData?.low_cell_pct != null && (
            <div className="shrink-0 text-[10px] text-gray-500 text-center py-0.5 border-t border-gray-100">
              Sample x CellType {'<='}10 cells: <span className="font-semibold text-red-600">{plotData.low_cell_pct}%</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
