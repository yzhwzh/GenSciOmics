import { useEffect, useState } from 'react'
import { Loader2, XCircle } from 'lucide-react'
import { cachedFetch } from '../../api/client'
import FilterDropdown from '../FilterDropdown'
import type { MutestResult } from '../../api/types'

export default function MuTestTable({
  realPath,
  gene,
  minCells,
  conditionCol = 'Group',
  variant = 'both',
}: {
  realPath: string
  gene: string
  minCells?: number
  conditionCol?: string
  /** Which table(s) to render: 'mean', 'pct', or 'both' */
  variant?: 'both' | 'mean' | 'pct'
}) {
  const [data, setData] = useState<MutestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [pairFilter, setPairFilter] = useState<Set<string> | undefined>(undefined)

  useEffect(() => {
    if (!realPath || !gene) return
    setLoading(true)
    const params = new URLSearchParams({ real_path: realPath, genes: gene, group_col: conditionCol })
    if (minCells !== undefined) { params.set('min_cells', String(minCells)) }
    cachedFetch<MutestResult>(`/api/per-sample-mutest?${params}`)
      .then(d => {
        if (d.pairs) setData(d)
        else console.error('MU test error:', (d as any).error)
      }).catch(e => console.error(e))
      .finally(() => setLoading(false))
  }, [realPath, gene, minCells, conditionCol])

  if (loading) return <div className="flex items-center justify-center py-4 text-xs text-gray-400"><Loader2 className="w-4 h-4 animate-spin mr-1" />Loading MU test...</div>
  if (!data) return <div className="text-xs text-gray-400 py-4 text-center">No MU test data</div>

  const maxCt = 30

  const handleToggle = (value: string) => {
    setPairFilter(prev => {
      const next = new Set(prev ?? [])
      if (next.has(value)) {
        next.delete(value)
      } else {
        next.add(value)
      }
      return next.size > 0 ? next : undefined
    })
  }

  const clearPairFilter = () => setPairFilter(undefined)

  const filteredPairs = pairFilter && pairFilter.size > 0
    ? data.pairs.filter(p => pairFilter.has(p))
    : data.pairs

  const getFilteredMatrix = (matrix: (number | null)[][]) => {
    if (!pairFilter || pairFilter.size === 0) return matrix
    return data.pairs
      .map((p, i) => ({ pair: p, row: matrix[i] }))
      .filter(({ pair }) => pairFilter.has(pair))
      .map(({ row }) => row)
  }

  const renderTable = (title: string, matrix: (number | null)[][]) => {
    const filteredMatrix = getFilteredMatrix(matrix)
    return (
      <div className="mb-2">
        <div className="text-[10px] font-semibold text-gray-500 px-1 pb-0.5">{title}</div>
        <table className="w-full text-[10px] border-collapse">
          <thead>
            <tr className="bg-gray-50 text-gray-500 sticky top-0 z-10">
              <th className="px-1.5 py-1 text-left font-medium whitespace-nowrap border-r border-gray-200">
                <FilterDropdown
                  label="Pair"
                  values={data.pairs}
                  selectedValues={pairFilter}
                  onToggle={handleToggle}
                  onClear={clearPairFilter}
                  isActive={!!pairFilter}
                />
              </th>
              {data.cell_types.slice(0, maxCt).map(ct => (
                <th key={ct} className="px-1.5 py-1 text-right font-medium whitespace-nowrap border-r border-gray-200 last:border-r-0" title={ct}>
                  {ct.length > 10 ? ct.slice(0, 10) + '...' : ct}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredPairs.map((pair, pi) => (
              <tr key={pair} className="border-t border-gray-100 hover:bg-gray-50">
                <td className="px-1.5 py-0.5 text-gray-700 font-medium border-r border-gray-100">{pair.replace('_vs_', ' vs ')}</td>
                {(filteredMatrix[pi] ?? []).slice(0, maxCt).map((pVal, ci) => {
                  const sig = pVal !== null && pVal <= 0.05
                  const valStr = pVal === null ? '-' : pVal < 0.001 ? '<0.001' : pVal.toFixed(4)
                  return (
                    <td key={ci}
                      className={`px-1.5 py-0.5 text-right font-mono border-r border-gray-100 ${sig ? 'text-red-600 font-bold bg-red-50' : 'text-gray-600'}`}>
                      {valStr}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {data.cell_types.length > maxCt && (
          <div className="text-[9px] text-gray-400 text-center py-0.5">Showing {maxCt} of {data.cell_types.length} cell types</div>
        )}
      </div>
    )
  }

  const showMean = variant === 'both' || variant === 'mean'
  const showPct = variant === 'both' || variant === 'pct'

  return (
    <div className="overflow-auto max-h-full px-2 py-1">
      <div className="flex items-center gap-2 px-1 pb-1 min-h-[18px]">
        {pairFilter && (
          <button onClick={clearPairFilter} className="inline-flex items-center gap-1 text-[10px] text-blue-600 hover:text-blue-800">
            <XCircle className="w-3 h-3" />
            Clear pair filter
          </button>
        )}
      </div>
      {showMean && renderTable('Mean Expression — MU test P-values', data.mean_matrix)}
      {showMean && showPct && <div className="border-t border-gray-200 my-1" />}
      {showPct && renderTable('Expression % — MU test P-values', data.pct_matrix)}
    </div>
  )
}
