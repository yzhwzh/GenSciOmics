import { useEffect, useState, useRef } from 'react'
import { Loader2, Download } from 'lucide-react'
import { useTableFilter } from '../../hooks/useTableFilter'
import FilterDropdown from '../FilterDropdown'
import { searchGenes, fetchBulkBoxplot, fetchBulkVolcano, fetchBulkDe, fetchBulkDiseases } from '../../api/analysis'
import { PALETTE_OPTIONS, type BulkDeRow } from '../../api/types'
import ZoomableImage from './ZoomableImage'

function fmtP(v: number | null): string {
  if (v === null) return 'NA'
  if (v === 0) return '0'
  if (v < 0.001) return v.toExponential(2)
  return v.toFixed(4)
}

function fmtNum(v: number | null, digits = 3): string {
  return v === null ? 'NA' : v.toFixed(digits)
}

// When no gene filter is active, render only the top N by padj to keep the DOM light;
// the full gene list is still loaded so the filter dropdown works across all genes.
const DISPLAY_LIMIT = 100

export default function BulkAnalysisTab({ realPath }: { realPath: string }) {
  // Shared controls
  const [disease, setDisease] = useState('All')
  const [diseases, setDiseases] = useState<string[]>([])
  const [gene, setGene] = useState(() => {
    try { return sessionStorage.getItem('gensci_bulk_gene') ?? 'TP53' } catch { return 'TP53' }
  })
  const [palette, setPalette] = useState('default')

  // Gene search autocomplete
  const geneSearchRef = useRef<HTMLDivElement>(null)
  const [geneInput, setGeneInput] = useState('')
  const [geneSuggestions, setGeneSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)

  // Boxplot
  const [boxplotSrc, setBoxplotSrc] = useState<string | null>(null)
  const [boxplotLoading, setBoxplotLoading] = useState(false)
  const [boxplotErr, setBoxplotErr] = useState('')

  // Volcano
  const [volcanoSrc, setVolcanoSrc] = useState<string | null>(null)
  const [volcanoCounts, setVolcanoCounts] = useState<{ n_up?: number; n_down?: number; n_ns?: number }>({})
  const [volcanoLoading, setVolcanoLoading] = useState(false)
  const [volcanoErr, setVolcanoErr] = useState('')

  // DE table
  const [rows, setRows] = useState<BulkDeRow[]>([])
  const [meta, setMeta] = useState<{ n_total?: number; n_tumor?: number; n_normal?: number }>({})
  const [deLoading, setDeLoading] = useState(false)
  const [deErr, setDeErr] = useState('')
  const [downloading, setDownloading] = useState(false)

  const {
    filteredRows, uniqueValues, toggleFilter, setColumnFilter, clearFilter, clearAllFilters, isFilterActive, filters,
  } = useTableFilter(rows as unknown as Record<string, unknown>[])
  const hasActiveFilters = Object.values(filters).some((s) => s.size > 0)
  const allRows = filteredRows as unknown as BulkDeRow[]
  const displayRows = hasActiveFilters ? allRows : allRows.slice(0, DISPLAY_LIMIT)

  useEffect(() => { try { sessionStorage.setItem('gensci_bulk_gene', gene) } catch { /* ignore */ } }, [gene])

  useEffect(() => {
    if (!realPath) return
    fetchBulkDiseases(realPath).then(setDiseases).catch(() => setDiseases([]))
  }, [realPath])

  // Gene autocomplete (debounced)
  useEffect(() => {
    if (!realPath || geneInput.length < 1) { setGeneSuggestions([]); return }
    const timer = setTimeout(() => {
      searchGenes(realPath, geneInput).then((genes) => { setGeneSuggestions(genes); setShowSuggestions(true) }).catch(() => setGeneSuggestions([]))
    }, 200)
    return () => clearTimeout(timer)
  }, [realPath, geneInput])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (geneSearchRef.current && !geneSearchRef.current.contains(e.target as Node)) setShowSuggestions(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Boxplot
  useEffect(() => {
    if (!realPath || !gene) return
    setBoxplotLoading(true); setBoxplotErr(''); setBoxplotSrc(null)
    fetchBulkBoxplot(realPath, gene, disease === 'All' ? undefined : disease, palette)
      .then((d) => {
        if (d.error) setBoxplotErr(d.error)
        else if (d.image) setBoxplotSrc(`data:image/png;base64,${d.image}`)
      })
      .catch((e) => setBoxplotErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBoxplotLoading(false))
  }, [realPath, gene, disease, palette])

  // Volcano
  useEffect(() => {
    if (!realPath) return
    setVolcanoLoading(true); setVolcanoSrc(null); setVolcanoErr('')
    fetchBulkVolcano(realPath, disease === 'All' ? undefined : disease)
      .then((d) => {
        if (d.error) { setVolcanoSrc(null); setVolcanoCounts({}); setVolcanoErr(d.error) }
        else if (d.image) {
          setVolcanoSrc(`data:image/png;base64,${d.image}`)
          setVolcanoCounts({ n_up: d.n_up, n_down: d.n_down, n_ns: d.n_ns })
        }
      })
      .catch((e) => { setVolcanoSrc(null); setVolcanoCounts({}); setVolcanoErr(e instanceof Error ? e.message : String(e)) })
      .finally(() => setVolcanoLoading(false))
  }, [realPath, disease])

  // DE table
  useEffect(() => {
    if (!realPath) return
    setDeLoading(true); setDeErr('')
    fetchBulkDe(realPath, disease === 'All' ? undefined : disease, 0)
      .then((d) => {
        if (d.error) { setDeErr(d.error); setRows([]) }
        else {
          setRows(d.genes ?? [])
          setMeta({ n_total: d.n_total, n_tumor: d.n_tumor, n_normal: d.n_normal })
        }
      })
      .catch((e) => { setDeErr(e.message); setRows([]) })
      .finally(() => setDeLoading(false))
  }, [realPath, disease])

  const downloadCSV = () => {
    if (!rows.length || downloading) return
    setDownloading(true)
    try {
      const header = ['Gene', 'Mean_Tumor', 'Mean_Normal', 'log2FC', 'pvalue', 'padj']
      const lines = [header.join(',')]
      for (const r of rows) {
        lines.push([r.gene, r.mean_tumor, r.mean_normal, r.log2fc, r.pvalue, r.padj].join(','))
      }
      const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `bulk_de_${disease === 'All' ? 'all' : disease}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setDownloading(false)
    }
  }

  const selectGene = (g: string) => { setGene(g); setGeneInput(''); setShowSuggestions(false) }

  return (
    <div className="h-full flex flex-col p-3 gap-2 overflow-hidden">
      {/* Top control bar */}
      <div className="flex items-center gap-3 shrink-0 flex-wrap">
        <div className="relative" ref={geneSearchRef}>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Gene</label>
          <input type="text" value={geneInput}
            onChange={(e) => { setGeneInput(e.target.value); setShowSuggestions(false) }}
            onFocus={() => { if (geneSuggestions.length) setShowSuggestions(true) }}
            onKeyDown={(e) => { if (e.key === 'Enter' && geneInput.trim()) selectGene(geneInput.trim()) }}
            onBlur={() => { if (geneInput.trim()) selectGene(geneInput.trim()) }}
            placeholder={gene || 'Search...'}
            className="w-[140px] text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-primary outline-none focus:border-brand font-medium" />
          {showSuggestions && geneSuggestions.length > 0 && (
            <div className="absolute top-full left-0 mt-0.5 bg-surface border border-border-light rounded-md shadow-overlay z-20 max-h-[180px] overflow-y-auto w-[220px]">
              {geneSuggestions.map((g) => (
                <button key={g} onClick={() => selectGene(g)}
                  className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-surface-muted text-text-secondary border-b border-border-light last:border-0">{g}</button>
              ))}
            </div>
          )}
        </div>

        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Disease</label>
          <select value={disease} onChange={(e) => setDisease(e.target.value)}
            className="text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-secondary outline-none focus:border-brand min-w-[140px]">
            <option value="All">All</option>
            {diseases.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>

        <div>
          <label className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">Palette</label>
          <select value={palette} onChange={(e) => setPalette(e.target.value)}
            className="text-xs border border-border-light rounded-sm px-2 py-1.5 bg-surface text-text-secondary outline-none focus:border-brand">
            {PALETTE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        {meta.n_total !== undefined && (
          <span className="text-xs text-text-muted mt-4">
            {meta.n_tumor ?? 0} Tumor vs {meta.n_normal ?? 0} Normal · {meta.n_total} genes tested
          </span>
        )}

        <div className="flex-1" />
        <button onClick={downloadCSV} disabled={downloading}
          className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-brand bg-surface border border-border-light hover:border-brand rounded-lg px-3 py-2 transition-colors disabled:opacity-50 mt-4">
          <Download className="w-3.5 h-3.5" /> {downloading ? 'Preparing...' : 'Download CSV'}
        </button>
      </div>

      {/* Top row: boxplot (left) + volcano (right) */}
      <div className="h-[44%] shrink-0 flex gap-2">
        <div className="flex-1 min-w-0 bg-surface rounded-md shadow-card overflow-hidden relative flex items-center justify-center">
          <div className="absolute top-2 left-3 text-[10px] font-semibold text-text-muted uppercase tracking-wider z-10">
            Gene Expression
          </div>
          {boxplotLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-surface/60 z-10">
              <Loader2 className="w-5 h-5 text-brand animate-spin" />
            </div>
          )}
          {!boxplotLoading && boxplotErr && <div className="text-sm text-text-muted p-4 text-center">{boxplotErr}</div>}
          {!boxplotLoading && !boxplotErr && !boxplotSrc && <div className="text-sm text-text-muted p-4">Select a gene to plot</div>}
          {boxplotSrc && <ZoomableImage src={boxplotSrc} alt="bulk boxplot" className="max-w-full max-h-full object-contain" />}
        </div>

        <div className="flex-1 min-w-0 bg-surface rounded-md shadow-card overflow-hidden relative flex items-center justify-center">
          <div className="absolute top-2 left-3 text-[10px] font-semibold text-text-muted uppercase tracking-wider z-10">
            Volcano Plot
          </div>
          {volcanoLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-surface/60 z-10">
              <Loader2 className="w-5 h-5 text-brand animate-spin" />
            </div>
          )}
          {!volcanoLoading && !volcanoSrc && (
            <div className="text-sm text-text-muted p-4 text-center">
              {volcanoErr ? `Volcano plot error: ${volcanoErr}` : 'Volcano plot unavailable'}
            </div>
          )}
          {volcanoSrc && (
            <>
              <ZoomableImage src={volcanoSrc} alt="volcano plot" className="max-w-full max-h-full object-contain" />
              {volcanoCounts.n_up !== undefined && (
                <div className="absolute bottom-2 right-3 flex items-center gap-3 text-[11px] font-medium bg-surface/80 rounded-md px-2 py-1 z-10">
                  <span className="text-error">▲ {volcanoCounts.n_up} up</span>
                  <span className="text-brand">▼ {volcanoCounts.n_down} down</span>
                  <span className="text-text-muted">{volcanoCounts.n_ns} n.s.</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Bottom: DE results table */}
      <div className="flex-1 min-h-0 bg-surface rounded-md shadow-card overflow-auto">
        <div className="sticky top-0 bg-surface-raised border-b border-border-light px-4 py-1.5 flex items-center justify-between gap-3 z-10">
          <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider shrink-0">
            {hasActiveFilters
              ? `Differential Expression Results (${displayRows.length}/${rows.length} matched)`
              : `Differential Expression Results (top ${DISPLAY_LIMIT} of ${rows.length} genes)`}
          </span>
          {hasActiveFilters && (
            <button onClick={clearAllFilters} className="text-[10px] text-brand hover:text-brand-dark shrink-0">Clear filter</button>
          )}
        </div>
        {deLoading ? (
          <div className="flex items-center justify-center h-40">
            <Loader2 className="w-6 h-6 text-brand animate-spin" />
          </div>
        ) : deErr ? (
          <div className="text-sm text-text-muted p-4 text-center">{deErr}</div>
        ) : displayRows.length === 0 ? (
          <div className="text-sm text-text-muted p-4 text-center">
            {hasActiveFilters ? 'No genes match the selected filters' : 'No results'}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-[30px] bg-surface-raised border-b border-border-light">
              <tr>
                <th className="text-left py-2.5 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                  <FilterDropdown
                    label="Gene"
                    values={uniqueValues['gene'] ?? []}
                    selectedValues={filters['gene']}
                    onToggle={(v) => toggleFilter('gene', v)}
                    onSetAll={(v) => setColumnFilter('gene', v)}
                    onClear={() => clearFilter('gene')}
                    isActive={isFilterActive('gene')}
                    portal
                  />
                </th>
                <th className="text-right py-2.5 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Mean (Tumor)</th>
                <th className="text-right py-2.5 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Mean (Normal)</th>
                <th className="text-right py-2.5 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">log2FC</th>
                <th className="text-right py-2.5 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">p-value</th>
                <th className="text-right py-2.5 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">FDR (padj)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {displayRows.map((r, i) => (
                <tr key={`${r.gene}-${i}`} className="hover:bg-surface-muted/60">
                  <td className="py-2 px-4 font-medium text-text-primary font-mono">{r.gene}</td>
                  <td className="py-2 px-4 text-right text-text-secondary tabular-nums">{fmtNum(r.mean_tumor)}</td>
                  <td className="py-2 px-4 text-right text-text-secondary tabular-nums">{fmtNum(r.mean_normal)}</td>
                  <td className={`py-2 px-4 text-right tabular-nums font-medium ${r.log2fc === null ? 'text-text-muted' : r.log2fc >= 0 ? 'text-brand' : 'text-error'}`}>
                    {r.log2fc === null ? 'NA' : `${r.log2fc >= 0 ? '+' : ''}${r.log2fc.toFixed(3)}`}
                  </td>
                  <td className="py-2 px-4 text-right text-text-secondary tabular-nums">{fmtP(r.pvalue)}</td>
                  <td className="py-2 px-4 text-right text-text-secondary tabular-nums">{fmtP(r.padj)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
