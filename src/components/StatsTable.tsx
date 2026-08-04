import { useEffect, useState } from 'react'
import { XCircle } from 'lucide-react'
import { fetchStats } from '../api/datasets'
import FilterDropdown from './FilterDropdown'
import type { StatsResponse } from '../api/types'

const ALL_SPECIES = ['Human', 'Mouse', 'Monkey']

export default function StatsTable() {
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tissueFilter, setTissueFilter] = useState<Set<string> | undefined>(undefined)

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch(() => setError('Failed to load statistics'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <section>
      <h2 className="text-[15px] font-semibold text-text-primary mb-3">
        Dataset Statistics by Tissue
      </h2>
      <div className="bg-surface rounded-xl shadow-card p-8">
        <div className="animate-pulse space-y-4">
          <div className="h-4 bg-surface-muted rounded w-1/3" />
          <div className="h-20 bg-surface-muted rounded" />
          <div className="h-4 bg-surface-muted rounded w-1/2" />
        </div>
      </div>
    </section>
  )
  if (error) return (
    <section>
      <h2 className="text-[15px] font-semibold text-text-primary mb-3">Dataset Statistics by Tissue</h2>
      <div className="bg-surface rounded-xl shadow-card p-6 text-center text-sm text-text-muted">{error}</div>
    </section>
  )
  if (!stats || stats.tissues.length === 0) return null

  const filteredTissues = tissueFilter && tissueFilter.size > 0
    ? stats.tissues.filter(t => tissueFilter.has(t))
    : stats.tissues

  const handleTissueToggle = (value: string) => {
    setTissueFilter(prev => {
      const next = new Set(prev ?? [])
      if (next.has(value)) {
        next.delete(value)
      } else {
        next.add(value)
      }
      return next.size > 0 ? next : undefined
    })
  }

  const clearFilter = () => setTissueFilter(undefined)

  return (
    <section>
      <h2 className="text-[15px] font-semibold text-text-primary mb-3">
        Dataset Statistics by Tissue
      </h2>
      <div className="bg-surface rounded-xl shadow-card overflow-x-auto max-h-[380px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="bg-surface-raised border-b border-border-light">
              <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                <div className="flex items-center gap-2">
                  <FilterDropdown
                    label="Tissue"
                    values={[...stats.tissues].sort()}
                    selectedValues={tissueFilter}
                    onToggle={handleTissueToggle}
                    onClear={clearFilter}
                    isActive={!!tissueFilter}
                  />
                  {tissueFilter && (
                    <button onClick={clearFilter} className="text-brand hover:text-brand-dark" title="Clear filter">
                      <XCircle className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </th>
              {ALL_SPECIES.map((sp) => {
                const hCount = stats.species_health_counts?.[sp] ?? 0
                const dCount = stats.species_disease_counts?.[sp] ?? 0
                return (
                  <th key={sp} className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <span>{sp}</span>
                      {hCount + dCount > 0 && (
                        <span className="font-normal text-text-muted text-[10px] leading-tight">
                          <span className="text-success">{hCount}H</span>
                          <span className="mx-0.5">·</span>
                          <span>{dCount}D</span>
                        </span>
                      )}
                    </div>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {filteredTissues.map((tis) => (
              <tr key={tis} className="hover:bg-surface-muted/60 transition-colors">
                <td className="py-3 px-4 text-sm font-medium text-text-primary capitalize whitespace-nowrap">
                  {tis}
                </td>
                {ALL_SPECIES.map((sp) => {
                  const cell = stats.rows[tis]?.[sp]
                  const diseases = cell?.diseases ?? []
                  return (
                    <td key={sp} className="py-3 px-4">
                      {!cell || diseases.length === 0 ? (
                        <span className="text-xs text-text-muted">-</span>
                      ) : (
                        <div className="flex flex-wrap gap-x-3 gap-y-1">
                          {diseases.map((d) => (
                            <span key={d.name} className="text-xs text-text-secondary whitespace-nowrap">
                              {d.name} <span className="font-medium text-text-primary">{d.count}</span>
                            </span>
                          ))}
                          <span className="text-[11px] text-text-muted border-l border-border-light pl-3">
                            {cell.total_datasets} dataset{cell.total_datasets > 1 ? 's' : ''}
                          </span>
                        </div>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
