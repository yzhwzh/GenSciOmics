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
}: {
  realPath: string
  gene: string
  conditionCol?: string
}) {
  const [data, setData] = useState<FisherTableData | null>(null)
  const [loading, setLoading] = useState(false)
  const [pairFilter, setPairFilter] = useState<Set<string> | undefined>(undefined)

  // Always call hooks before early return (React rules)
  useEffect(() => {
    if (!realPath || !gene || conditionCol === 'None') { setData(null); return }
    setLoading(true)
    const params = new URLSearchParams({ real_path: realPath, genes: gene, group_col: 'Group' })
    cachedFetch<FisherTableData>(`/api/aggregate-table?${params}`)
      .then(d => {
        if (d.fisher) setData(d)
        else console.error('Fisher error:', (d as any).error)
      }).catch(e => console.error(e))
      .finally(() => setLoading(false))
  }, [realPath, gene, conditionCol])

  // When no condition, Fisher test is not applicable
  if (conditionCol === 'None') {
    return <div className="text-xs text-gray-400 py-4 text-center">Fisher test requires a condition (Group) to compare. Select <strong>Group</strong> as Condition.</div>
  }

  if (loading) return <div className="flex items-center justify-center py-4 text-xs text-gray-400"><Loader2 className="w-4 h-4 animate-spin mr-1" />Loading...</div>
  if (!data?.fisher) return <div className="text-xs text-gray-400 py-4 text-center">No data</div>

  const { fisher } = data
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
    ? fisher.pairs.filter(p => pairFilter.has(p))
    : fisher.pairs

  const filteredMatrix = pairFilter && pairFilter.size > 0
    ? fisher.pairs
        .map((p, i) => ({ pair: p, row: fisher.matrix[i] }))
        .filter(({ pair }) => pairFilter.has(pair))
        .map(({ row }) => row)
    : fisher.matrix

  return (
    <div className="overflow-auto max-h-full">
      <div className="flex items-center gap-2 px-2 py-0.5 min-h-[18px]">
        {pairFilter && (
          <button onClick={clearPairFilter} className="inline-flex items-center gap-1 text-[10px] text-blue-600 hover:text-blue-800">
            <XCircle className="w-3 h-3" />
            Clear pair filter
          </button>
        )}
      </div>
      <table className="w-full text-[10px] border-collapse">
        <thead>
          <tr className="bg-gray-50 text-gray-500 sticky top-0 z-10">
            <th className="px-1.5 py-1 text-left font-medium whitespace-nowrap border-r border-gray-200">
              <FilterDropdown
                label="Pair"
                values={fisher.pairs}
                selectedValues={pairFilter}
                onToggle={handleToggle}
                onClear={clearPairFilter}
                isActive={!!pairFilter}
              />
            </th>
            {fisher.cell_types.slice(0, maxCt).map(ct => (
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
      {fisher.cell_types.length > maxCt && (
        <div className="text-[9px] text-gray-400 text-center py-0.5">Showing {maxCt} of {fisher.cell_types.length} cell types</div>
      )}
    </div>
  )
}
