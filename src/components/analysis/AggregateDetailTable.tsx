import { useEffect, useState } from 'react'
import { Loader2, XCircle } from 'lucide-react'
import { cachedFetch } from '../../api/client'
import { useTableFilter } from '../../hooks/useTableFilter'
import FilterDropdown from '../FilterDropdown'
import type { AggregateRow, FisherResult } from '../../api/types'

interface AggregateTableData {
  rows: AggregateRow[]
  groups: string[]
  fisher: FisherResult
}

const STAT_COLS = [
  { key: 'CellTypeNumber' as const, label: 'Cell #' },
  { key: 'CellTotalNumber' as const, label: 'Total Cells' },
  { key: 'CellTypeRatio' as const, label: 'Ratio %' },
  { key: 'GeneMeanExpression' as const, label: 'Mean Expr.' },
  { key: 'GeneExpressionPct' as const, label: 'Expr. %' },
  { key: 'GeneExpressionNumber' as const, label: 'Expr. #' },
]
type StatKey = (typeof STAT_COLS)[number]['key']

export default function AggregateDetailTable({
  realPath,
  gene,
  conditionCol = 'Group',
}: {
  realPath: string
  gene: string
  conditionCol?: string
}) {
  const [data, setData] = useState<AggregateTableData | null>(null)
  const [loading, setLoading] = useState(false)

  // Always call hook at top level (empty rows until data loads)
  const {
    filteredRows, getUniqueValues, toggleFilter, setColumnFilter, clearFilter, clearAllFilters, isFilterActive, filters,
  } = useTableFilter((data?.rows ?? []) as unknown as Record<string, unknown>[])

  useEffect(() => {
    if (!realPath || !gene) return
    setLoading(true)
    const groupCol = conditionCol === 'None' ? '' : 'Group'
    const params = new URLSearchParams({ real_path: realPath, genes: gene, group_col: groupCol })
    cachedFetch<AggregateTableData>(`/api/aggregate-table?${params}`)
      .then(d => {
        if (d.rows) setData(d)
        else console.error('Aggregate table error:', (d as any).error)
      }).catch(e => console.error(e))
      .finally(() => setLoading(false))
  }, [realPath, gene, conditionCol])

  if (loading) return <div className="flex items-center justify-center py-4 text-xs text-text-muted"><Loader2 className="w-4 h-4 animate-spin mr-1" />Loading...</div>
  if (!data?.rows.length) return <div className="text-xs text-text-muted py-4 text-center">No data</div>

  const { rows, groups } = data
  const activeRows = filteredRows as unknown as AggregateRow[]
  const cellTypes = [...new Set(activeRows.map(r => r.CellType))]
  const genes = [...new Set(activeRows.map(r => r.Gene))]
  const hasActiveFilters = Object.values(filters).some(s => s.size > 0)

  const lookup = new Map<string, AggregateRow>()
  for (const r of activeRows) lookup.set(`${r.Gene}|${r.CellType}|${r.Group}`, r)

  const STAT_COLS_SHORT = STAT_COLS.map(sc => sc.label)
  const COL_HEADERS: { label: string; key: string; group?: string }[] = [
    { label: 'Gene', key: '_gene' },
    { label: 'CellType', key: '_ct' },
  ]
  if (groups.length === 0) {
    // Ungrouped mode: show stats directly without group prefix
    for (const sc of STAT_COLS) {
      COL_HEADERS.push({ label: sc.label, key: sc.key })
    }
  } else {
    for (const g of groups) {
      for (const sc of STAT_COLS) {
        COL_HEADERS.push({ label: `${sc.label}_${g}`, key: `${sc.key}|${g}`, group: g })
      }
    }
  }

  const downloadCSV = () => {
    const csvRows = [COL_HEADERS.map(c => c.label).join(',')]
    for (const ct of cellTypes) {
      for (const gn of genes) {
        const vals = COL_HEADERS.map(ch => {
          if (ch.key === '_gene') return gn
          if (ch.key === '_ct') return ct
          const [statKey, grp] = ch.key.split('|')
          const r = lookup.get(`${gn}|${ct}|${grp}`)
          if (!r) return ''
          const v = r[statKey as StatKey]
          return v != null ? String(v) : ''
        })
        csvRows.push(vals.join(','))
      }
    }
    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'aggregate_detail.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="overflow-auto max-h-full">
      <div className="flex items-center justify-between px-2 py-0.5">
        <div className="flex items-center gap-2">
          {hasActiveFilters && (
            <>
              <button onClick={clearAllFilters} className="inline-flex items-center gap-1 text-[10px] text-brand hover:text-brand-dark">
                <XCircle className="w-3 h-3" />
                Clear filters
              </button>
              <span className="text-[10px] text-text-muted">
                {cellTypes.length} cell types, {genes.length} genes
              </span>
            </>
          )}
        </div>
        <button onClick={downloadCSV} className="text-[10px] text-brand hover:text-brand-dark hover:underline font-medium">Download CSV</button>
      </div>
      <table className="w-full text-[10px] border-collapse">
        <thead>
          <tr className="bg-surface-muted text-text-secondary sticky top-0 z-10">
            <th colSpan={1} className="px-1.5 py-0.5 text-left font-semibold border-r border-border-medium">
              <FilterDropdown
                label="Gene"
                values={getUniqueValues('Gene')}
                selectedValues={filters['Gene']}
                onToggle={(v) => toggleFilter('Gene', v)}
                onSetAll={(v) => setColumnFilter('Gene', v)}
                onClear={() => clearFilter('Gene')}
                isActive={isFilterActive('Gene')}
                portal
              />
            </th>
            <th colSpan={1} className="px-1.5 py-0.5 text-left font-semibold border-r border-border-medium">
              <FilterDropdown
                label="CellType"
                values={getUniqueValues('CellType')}
                selectedValues={filters['CellType']}
                onToggle={(v) => toggleFilter('CellType', v)}
                onSetAll={(v) => setColumnFilter('CellType', v)}
                onClear={() => clearFilter('CellType')}
                isActive={isFilterActive('CellType')}
                portal
              />
            </th>
            {groups.length === 0 ? (
              <th colSpan={STAT_COLS.length} className="px-1.5 py-0.5 text-center font-semibold border-r border-border-medium bg-gray-100 text-text-muted text-[9px]">All Cells</th>
            ) : groups.map(g => (
              <th key={g} colSpan={STAT_COLS.length} className="px-1.5 py-0.5 text-center font-semibold border-r border-border-medium bg-gray-100">{g}</th>
            ))}
          </tr>
          <tr className="bg-surface-raised text-text-muted sticky top-[22px] z-10">
            <th className="px-1.5 py-0.5 text-left font-medium border-r border-border-light">&nbsp;</th>
            <th className="px-1.5 py-0.5 text-left font-medium border-r border-border-light">&nbsp;</th>
            {groups.length === 0 ? (
              STAT_COLS_SHORT.map((label, si) => (
                <th key={si} className="px-1 py-0.5 text-right font-medium whitespace-nowrap border-r border-border-light last:border-r-0">{label}</th>
              ))
            ) : groups.map(g => STAT_COLS_SHORT.map((label, si) => (
              <th key={`${g}|${si}`} className="px-1 py-0.5 text-right font-medium whitespace-nowrap border-r border-border-light last:border-r-0">{label}</th>
            )))}
          </tr>
        </thead>
        <tbody>
          {cellTypes.map(ct =>
            genes.map(gn => {
              const cells = COL_HEADERS.map(ch => {
                if (ch.key === '_gene') return <td key="g" className="px-1.5 py-0.5 text-text-secondary border-r border-border-light font-medium">{gn}</td>
                if (ch.key === '_ct') return <td key="ct" className="px-1.5 py-0.5 text-text-secondary border-r border-border-light">{ct}</td>
                const parts = ch.key.split('|')
                const statKey = parts[0]
                const grp = parts.length > 1 ? parts[1] : ''
                const lookupKey = grp ? `${gn}|${ct}|${grp}` : `${gn}|${ct}|`
                const r = lookup.get(lookupKey)
                let val: string | number = ''
                if (r) {
                  const v = r[statKey as StatKey]
                  val = typeof v === 'number' && statKey === 'GeneMeanExpression' ? v.toFixed(4)
                    : typeof v === 'number' && (statKey === 'CellTypeRatio' || statKey === 'GeneExpressionPct') ? v.toFixed(2)
                    : v ?? ''
                }
                return <td key={ch.key} className="px-1.5 py-0.5 text-right text-text-secondary border-r border-border-light">{val}</td>
              })
              return <tr key={`${gn}|${ct}`} className="border-t border-border-light hover:bg-surface-raised">{cells}</tr>
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
