import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { ExternalLink, Loader2, Search, XCircle } from 'lucide-react'
import { searchDatasets } from '../api/search'
import Header from '../components/Header'
import { useTableFilter } from '../hooks/useTableFilter'
import FilterDropdown from '../components/FilterDropdown'
import type { SearchMatch } from '../api/types'

const MATCH_LABELS: Record<string, { label: string; color: string }> = {
  gene: { label: 'Gene', color: 'bg-blue-100 text-brand-dark' },
  disease: { label: 'Disease', color: 'bg-purple-100 text-purple-700' },
  pmid: { label: 'PMID', color: 'bg-surface-muted text-text-secondary' },
  tissue: { label: 'Tissue', color: 'bg-green-100 text-success' },
  sample_type: { label: 'Sample Type', color: 'bg-teal-100 text-teal-700' },
  celltype: { label: 'CellType', color: 'bg-orange-100 text-orange-700' },
}

export default function SearchPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const query = searchParams.get('q') || ''
  const [results, setResults] = useState<SearchMatch[]>([])
  const [loading, setLoading] = useState(true)
  const {
    filteredRows, getUniqueValues, toggleFilter, clearFilter, clearAllFilters, isFilterActive, filters,
  } = useTableFilter(results)
  const hasActiveFilters = Object.values(filters).some(s => s.size > 0)

  useEffect(() => {
    if (!query) {
      setLoading(false)
      return
    }
    setLoading(true)
    searchDatasets(query)
      .then((data) => {
        setResults(Array.isArray(data.results) ? data.results : [])
      })
      .catch(() => setResults([]))
      .finally(() => setLoading(false))
  }, [query])

  return (
    <div className="min-h-screen bg-surface-raised/50">
      <Header />

      <div className="max-w-7xl mx-auto px-6 py-6">
        {/* Search header */}
        <div className="bg-surface rounded-xl border border-border-light shadow-card p-5 mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-100 flex items-center justify-center shrink-0">
              <Search className="w-5 h-5 text-brand" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-text-primary">
                Search results for &ldquo;{query}&rdquo;
              </h1>
              <p className="text-sm text-text-muted">
                {loading ? 'Searching...' : `${results.length} dataset(s) matched`}
                {hasActiveFilters && (
                  <span className="ml-2 text-brand">· {filteredRows.length} shown</span>
                )}
              </p>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="bg-surface rounded-xl border border-border-light shadow-card p-12 text-center">
            <Loader2 className="w-6 h-6 text-brand mx-auto mb-2 animate-spin" />
            <p className="text-sm text-text-muted">Searching datasets...</p>
          </div>
        ) : results.length === 0 ? (
          <div className="bg-surface rounded-xl border border-border-light shadow-card p-12 text-center">
            <p className="text-text-muted text-sm">
              No datasets matched &ldquo;{query}&rdquo;
            </p>
            <p className="text-xs text-text-muted mt-1">
              Try searching for a gene name (e.g. CD4), disease, cell type, or PMID
            </p>
          </div>
        ) : (
          <div className="bg-surface rounded-xl border border-border-light shadow-card overflow-x-auto">
            <div className="flex items-center justify-between px-4 pt-2 pb-0">
              <div>
                {hasActiveFilters && (
                  <button onClick={clearAllFilters}
                    className="inline-flex items-center gap-1 text-xs text-brand hover:text-brand-dark">
                    <XCircle className="w-3.5 h-3.5" />
                    Clear filters
                  </button>
                )}
              </div>
            </div>
            <table className="w-full text-sm min-w-[900px]">
              <thead>
                <tr className="bg-surface-raised border-b border-border-light">
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Match</th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                    <FilterDropdown
                      label="Species"
                      values={getUniqueValues('species')}
                      selectedValues={filters['species']}
                      onToggle={(v) => toggleFilter('species', v)}
                      onClear={() => clearFilter('species')}
                      isActive={isFilterActive('species')}
                      portal
                    />
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                    <FilterDropdown
                      label="Tissue"
                      values={getUniqueValues('tissue')}
                      selectedValues={filters['tissue']}
                      onToggle={(v) => toggleFilter('tissue', v)}
                      onClear={() => clearFilter('tissue')}
                      isActive={isFilterActive('tissue')}
                      portal
                    />
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                    <FilterDropdown
                      label="Disease"
                      values={getUniqueValues('disease')}
                      selectedValues={filters['disease']}
                      onToggle={(v) => toggleFilter('disease', v)}
                      onClear={() => clearFilter('disease')}
                      isActive={isFilterActive('disease')}
                      portal
                    />
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">PMID</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Patient</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Sample</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">CellType</th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider" title="Group distribution">Group</th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                    <FilterDropdown
                      label="Sample Type"
                      values={getUniqueValues('tissue_obs')}
                      selectedValues={filters['tissue_obs']}
                      onToggle={(v) => toggleFilter('tissue_obs', v)}
                      onClear={() => clearFilter('tissue_obs')}
                      isActive={isFilterActive('tissue_obs')}
                      portal
                    />
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {(hasActiveFilters ? filteredRows : results).map((row, i) => (
                  <tr key={i} className="hover:bg-surface-muted/60 transition-colors">
                    <td className="py-2.5 px-4">
                      <div className="flex flex-wrap gap-1">
                        {row.search_matches.slice(0, 3).map(([type, val]) => {
                          const info = MATCH_LABELS[type] || { label: type, color: 'bg-surface-muted text-text-secondary' }
                          return (
                            <span key={`${type}-${val}`} className={`inline-block text-[10px] font-medium px-1.5 py-0.5 rounded ${info.color}`}>
                              {info.label}:{val.length > 12 ? val.slice(0, 12) + '…' : val}
                            </span>
                          )
                        })}
                        {row.search_matches.length > 3 && (
                          <span className="text-[10px] text-text-muted">+{row.search_matches.length - 3}</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-4 text-sm text-text-secondary">{row.species ?? 'Human'}</td>
                    <td className="py-3 px-4 text-sm text-text-secondary capitalize">{row.tissue}</td>
                    <td className="py-3 px-4 text-sm font-medium text-text-primary">{row.disease}</td>
                    <td className="py-3 px-4">
                      <button
                        onClick={() => navigate(`/analysis/${row.tissue}/${row.disease}/${row.pmid}`)}
                        disabled={row.status !== 'ready'}
                        className={`inline-flex items-center gap-1 font-mono text-sm underline underline-offset-2 transition-colors ${
                          row.status === 'ready'
                            ? 'text-brand hover:text-brand-dark cursor-pointer'
                            : 'text-text-muted cursor-not-allowed'
                        }`}
                      >
                        {row.pmid}
                        {row.status === 'ready' && <ExternalLink className="w-3 h-3" />}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-sm text-text-secondary text-right tabular-nums">{row.patient_count ?? '-'}</td>
                    <td className="py-3 px-4 text-sm text-text-secondary text-right tabular-nums">{row.sample_count ?? '-'}</td>
                    <td className="py-3 px-4 text-sm text-text-secondary text-right tabular-nums">{row.celltype_count ?? '-'}</td>
                    <td className="py-2.5 px-4 text-xs text-text-secondary leading-snug break-words max-w-[240px]" title={row.group_dist}>
                      {row.group_dist || '-'}
                    </td>
                    <td className="py-3 px-4 text-sm text-text-secondary">{row.tissue_obs || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-4 text-xs text-text-muted">
          {results.length > 0 && `${results.length} dataset(s) matched`}
        </div>
      </div>
    </div>
  )
}
