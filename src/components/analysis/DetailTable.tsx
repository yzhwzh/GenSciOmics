import { useEffect, useState } from 'react'
import { Loader2, XCircle } from 'lucide-react'
import { cachedFetch } from '../../api/client'
import { useTableFilter } from '../../hooks/useTableFilter'
import FilterDropdown from '../FilterDropdown'
import type { PerSampleRow } from '../../api/types'

// Threshold: disable column filters when rows exceed this (DOM too heavy for re-render)
const FILTER_MAX_ROWS = 2000

const COLUMNS = [
  { key: 'SampleID', label: 'Sample', filterable: true },
  { key: 'CellType', label: 'CellType', filterable: true },
  { key: 'CellTypeNumber', label: 'Cell #', filterable: false },
  { key: 'CellTotalNumber', label: 'Total Cells', filterable: false },
  { key: 'CellTypeRatio', label: 'Ratio %', filterable: false },
  { key: 'Gene', label: 'Gene', filterable: true },
  { key: 'GeneMeanExpression', label: 'Mean Expression', filterable: false },
  { key: 'GeneExpressionPct', label: 'Expressing %', filterable: false },
  { key: 'GeneExpressionNumber', label: 'Expressing Cells #', filterable: false },
  { key: 'Group', label: 'Group', filterable: true },
]

export default function DetailTable({
  realPath,
  gene,
  conditionCol = 'Group',
}: {
  realPath: string
  gene: string
  conditionCol?: string
}) {
  const [rows, setRows] = useState<PerSampleRow[]>([])
  const [loading, setLoading] = useState(false)
  const {
    filteredRows, uniqueValues, toggleFilter, setColumnFilter, clearFilter, clearAllFilters, isFilterActive, filters,
  } = useTableFilter(rows as unknown as Record<string, unknown>[])

  useEffect(() => {
    if (!realPath || !gene) return
    setLoading(true)
    const params = new URLSearchParams({ real_path: realPath, genes: gene, group_col: conditionCol })
    cachedFetch<{ rows?: PerSampleRow[]; error?: string }>(`/api/per-sample-table?${params}`)
      .then(d => {
        if (d.rows) setRows(d.rows)
        else console.error('Table error:', d.error)
      }).catch(e => console.error(e))
      .finally(() => setLoading(false))
  }, [realPath, gene, conditionCol])

  if (loading) {
    return <div className="flex items-center justify-center py-4 text-xs text-text-muted"><Loader2 className="w-4 h-4 animate-spin mr-1" />Loading table...</div>
  }
  if (!rows.length) {
    return <div className="text-xs text-text-muted py-4 text-center">No data</div>
  }

  const downloadCSV = () => {
    const headers = COLUMNS.map(c => c.label)
    const csvRows = [headers.join(',')]
    for (const row of filteredRows as unknown as PerSampleRow[]) {
      const vals = COLUMNS.map(c => {
        const v = row[c.key as keyof PerSampleRow]
        return typeof v === 'string' && v.includes(',') ? `"${v}"` : String(v ?? '')
      })
      csvRows.push(vals.join(','))
    }
    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `per_sample_detail.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  const hasActiveFilters = Object.values(filters).some(s => s.size > 0)
  const tooLarge = rows.length > FILTER_MAX_ROWS

  return (
    <div className="overflow-auto">
      <div className="flex items-center justify-between px-2 py-0.5">
        <div className="flex items-center gap-2">
          {hasActiveFilters && (
            <button onClick={clearAllFilters}
              className="inline-flex items-center gap-1 text-[10px] text-brand hover:text-brand-dark">
              <XCircle className="w-3 h-3" />
              Clear filters
            </button>
          )}
          {hasActiveFilters && (
            <span className="text-[10px] text-text-muted">
              {filteredRows.length} / {rows.length} rows
            </span>
          )}
          {tooLarge && !hasActiveFilters && (
            <span className="text-[10px] text-text-muted italic">
              {rows.length} rows — filters disabled for performance
            </span>
          )}
        </div>
        <button onClick={downloadCSV}
          className="text-[10px] text-brand hover:text-brand-dark hover:underline font-medium">Download CSV</button>
      </div>
      <table className="w-full text-[10px] border-collapse">
        <thead>
          <tr className="bg-surface-raised text-text-muted sticky top-0 z-10">
            {COLUMNS.map(col => (
              <th key={col.key} className="px-1.5 py-1 text-left font-medium whitespace-nowrap border-r border-border-light last:border-r-0">
                {col.filterable && !tooLarge ? (
                  <FilterDropdown
                    label={col.label}
                    values={uniqueValues[col.key] ?? []}
                    selectedValues={filters[col.key]}
                    onToggle={(v) => toggleFilter(col.key, v)}
                    onSetAll={(v) => setColumnFilter(col.key, v)}
                    onClear={() => clearFilter(col.key)}
                    isActive={isFilterActive(col.key)}
                    portal
                  />
                ) : (
                  col.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(filteredRows as unknown as PerSampleRow[]).map((row, i) => (
            <tr key={i} className="border-t border-border-light hover:bg-surface-raised">
              <td className="px-1.5 py-0.5 text-text-secondary border-r border-border-light">{row.SampleID}</td>
              <td className="px-1.5 py-0.5 text-text-secondary border-r border-border-light">{row.CellType}</td>
              <td className="px-1.5 py-0.5 text-right text-text-secondary border-r border-border-light">{row.CellTypeNumber}</td>
              <td className="px-1.5 py-0.5 text-right text-text-secondary border-r border-border-light">{row.CellTotalNumber}</td>
              <td className="px-1.5 py-0.5 text-right text-text-secondary border-r border-border-light">{row.CellTypeRatio.toFixed(2)}</td>
              <td className="px-1.5 py-0.5 text-text-secondary border-r border-border-light font-medium">{row.Gene}</td>
              <td className="px-1.5 py-0.5 text-right text-text-secondary border-r border-border-light">{row.GeneMeanExpression.toFixed(4)}</td>
              <td className="px-1.5 py-0.5 text-right text-text-secondary border-r border-border-light">{row.GeneExpressionPct.toFixed(2)}</td>
              <td className="px-1.5 py-0.5 text-right text-text-secondary border-r border-border-light">{row.GeneExpressionNumber}</td>
              <td className="px-1.5 py-0.5 text-text-secondary">{row.Group}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
