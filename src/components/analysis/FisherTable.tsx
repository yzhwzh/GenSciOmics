import { useEffect, useState } from 'react'
import { Loader2, XCircle } from 'lucide-react'
import { cachedFetch } from '../../api/client'
import FilterDropdown from '../FilterDropdown'
import type { AggregateRow, FisherResult } from '../../api/types'

interface FisherTableData {
  rows: AggregateRow[]
  fisher: FisherResult
}

export default function FisherTable({
  realPath,
  gene,
  conditionCol = 'Group',
  gene2 = '',
  gene2Label = '',
}: {
  realPath: string
  gene: string
  conditionCol?: string
  gene2?: string
  gene2Label?: string
}) {
  const [data, setData] = useState<FisherTableData | null>(null)
  const [loading, setLoading] = useState(false)
  const [geneFilter, setGeneFilter] = useState<Set<string> | undefined>(undefined)
  const [pairFilter, setPairFilter] = useState<Set<string> | undefined>(undefined)

  // Always call hook at top level (Fisher requires a Group condition)
  useEffect(() => {
    if (!realPath || !gene || conditionCol === 'None') { setData(null); return }
    setLoading(true)
    const params = new URLSearchParams({ real_path: realPath, genes: gene, group_col: 'Group' })
    if (gene2?.trim()) params.set('gene2', gene2.trim())
    if (gene2Label?.trim()) params.set('gene2_label', gene2Label.trim())
    cachedFetch<FisherTableData>(`/api/aggregate-table?${params}`)
      .then(d => {
        if (d.fisher) setData(d)
        else console.error('Fisher error:', (d as any).error)
      }).catch(e => console.error(e))
      .finally(() => setLoading(false))
  }, [realPath, gene, conditionCol, gene2, gene2Label])

  // When no condition, Fisher test is not applicable
  if (conditionCol === 'None') {
    return <div className="text-xs text-text-muted py-4 text-center">Fisher test requires a condition (Group) to compare. Select <strong>Group</strong> as Condition.</div>
  }

  if (loading) return <div className="flex items-center justify-center py-4 text-xs text-text-muted"><Loader2 className="w-4 h-4 animate-spin mr-1" />Loading...</div>
  if (!data?.fisher?.rows?.length) return <div className="text-xs text-text-muted py-4 text-center">No data</div>

  const { fisher } = data
  const maxCt = 30
  const cellTypes = fisher.cell_types
  const geneList = [...new Set(fisher.rows.map(r => r.gene))]
  const pairList = [...new Set(fisher.rows.map(r => r.pair))]

  const toggleFilter = (kind: 'gene' | 'pair') => (value: string) => {
    const setter = kind === 'gene' ? setGeneFilter : setPairFilter
    setter(prev => {
      const next = new Set(prev ?? [])
      if (next.has(value)) {
        next.delete(value)
      } else {
        next.add(value)
      }
      return next.size > 0 ? next : undefined
    })
  }

  const clearFilters = () => {
    setGeneFilter(undefined)
    setPairFilter(undefined)
  }

  const visibleRows = fisher.rows.filter(r =>
    (!geneFilter || geneFilter.has(r.gene)) &&
    (!pairFilter || pairFilter.has(r.pair)),
  )

  return (
    <div className="overflow-auto max-h-full">
      <div className="flex items-center gap-2 px-2 py-0.5 min-h-[18px]">
        {(geneFilter || pairFilter) && (
          <button onClick={clearFilters} className="inline-flex items-center gap-1 text-[10px] text-brand hover:text-brand-dark">
            <XCircle className="w-3 h-3" />
            Clear filters
          </button>
        )}
        <span className="text-[9px] text-text-muted ml-auto">
          {visibleRows.length} of {fisher.rows.length} gene × pair rows
        </span>
      </div>
      <table className="w-full text-[10px] border-collapse">
        <thead>
          <tr className="bg-surface-raised text-text-muted sticky top-0 z-10">
            <th className="px-1.5 py-1 text-left font-medium whitespace-nowrap border-r border-border-light">
              <FilterDropdown
                label="Gene"
                values={geneList}
                selectedValues={geneFilter}
                onToggle={toggleFilter('gene')}
                onClear={() => setGeneFilter(undefined)}
                isActive={!!geneFilter}
              />
            </th>
            <th className="px-1.5 py-1 text-left font-medium whitespace-nowrap border-r border-border-light">
              <FilterDropdown
                label="Pair"
                values={pairList}
                selectedValues={pairFilter}
                onToggle={toggleFilter('pair')}
                onClear={() => setPairFilter(undefined)}
                isActive={!!pairFilter}
              />
            </th>
            {cellTypes.slice(0, maxCt).map(ct => (
              <th key={ct} className="px-1.5 py-1 text-right font-medium whitespace-nowrap border-r border-border-light last:border-r-0" title={ct}>
                {ct.length > 10 ? ct.slice(0, 10) + '...' : ct}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visibleRows.map(row => (
            <tr key={`${row.gene}|${row.pair}`} className="border-t border-border-light hover:bg-surface-raised">
              <td className="px-1.5 py-0.5 text-text-secondary font-medium border-r border-border-light">{row.gene}</td>
              <td className="px-1.5 py-0.5 text-text-secondary border-r border-border-light">{row.pair.replace('_vs_', ' vs ')}</td>
              {row.pvals.slice(0, maxCt).map((pVal, ci) => {
                const sig = pVal !== null && pVal <= 0.05
                const valStr = pVal === null ? '-' : pVal < 0.001 ? '<0.001' : pVal.toFixed(4)
                return (
                  <td key={ci}
                    className={`px-1.5 py-0.5 text-right font-mono border-r border-border-light ${sig ? 'text-red-600 font-bold bg-error-bg' : 'text-text-secondary'}`}>
                    {valStr}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {cellTypes.length > maxCt && (
        <div className="text-[9px] text-text-muted text-center py-0.5">Showing {maxCt} of {cellTypes.length} cell types</div>
      )}
    </div>
  )
}
