import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Download, ExternalLink, HardDrive, Loader2, XCircle, BookOpen, Dna, FlaskConical, Beaker, Microscope } from 'lucide-react'
import { fetchDatasets } from '../api/datasets'
import { ORGANS } from '../data/mockData'
import { useTableFilter } from '../hooks/useTableFilter'
import FilterDropdown from '../components/FilterDropdown'
import { LiteratureTab } from '../components/analysis'
import type { DatasetInfo } from '../api/types'

type OmicsTab = 'single-cell' | 'bulk-rna' | 'proteomics' | 'metabolomics' | 'literature'

const OMICS_TABS: { key: OmicsTab; label: string; icon: typeof Dna }[] = [
  { key: 'single-cell', label: 'Single Cell', icon: Microscope },
  { key: 'bulk-rna', label: 'Bulk RNA', icon: Dna },
  { key: 'proteomics', label: 'Proteomics', icon: Beaker },
  { key: 'metabolomics', label: 'Metabolomics', icon: FlaskConical },
]

export default function TissuePage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const [rows, setRows] = useState<DatasetInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<OmicsTab>('single-cell')
  const {
    filteredRows, getUniqueValues, toggleFilter, clearFilter, clearAllFilters, isFilterActive, filters,
  } = useTableFilter(rows)

  const organ = ORGANS.find((o) => o.slug === slug)
  const tissueName = organ?.label ?? slug ?? 'Unknown'
  const hasActiveFilters = Object.values(filters).some(s => s.size > 0)

  useEffect(() => {
    if (!slug) return
    setLoading(true)
    fetchDatasets(slug)
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [slug])

  useEffect(() => {
    if (!slug || loading) return
    const hasPending = rows.some((r) => r.status !== 'ready')
    if (!hasPending) return
    const interval = setInterval(() => {
      fetchDatasets(slug).then((data) => { if (Array.isArray(data)) setRows(data) }).catch(() => {})
    }, 5000)
    return () => clearInterval(interval)
  }, [slug, loading, rows])

  // single-cell = scRNA datasets; bulk-rna = BulkRNA datasets; others stay placeholder
  const omicsRows =
    activeTab === 'single-cell'
      ? rows.filter((r) => r.omics_type === 'scRNA')
      : activeTab === 'bulk-rna'
        ? rows.filter((r) => r.omics_type === 'BulkRNA')
        : activeTab === 'proteomics'
          ? rows.filter((r) => r.omics_type === 'Protein')
          : []
  // bulk-rna + proteomics 都是"表型级"数据:用 Genes / Data Type 列,无 Annotation Source
  const isTabular = activeTab === 'bulk-rna' || activeTab === 'proteomics'

  const downloadCSV = () => {
    const headers = ['Species', 'Disease', 'PMID', 'Size', 'Status', 'Patient', 'Sample', isTabular ? 'Genes' : 'CellTypes', 'Group']
    if (!isTabular) headers.push('Annotation Source')
    const csvRows = [headers.join(',')]
    for (const r of omicsRows) {
      const row = [
        r.species ?? 'Human', `"${r.disease}"`, r.pmid,
        r.size_mb && r.size_mb > 1000 ? `${(r.size_mb / 1024).toFixed(1)} GB` : `${r.size_mb} MB`,
        r.status, r.patient_count ?? '-', r.sample_count ?? '-',
        isTabular ? (r.n_vars ?? '-') : (r.celltype_count ?? '-'), `"${r.group_dist || '-'}"`,
      ]
      if (!isTabular) row.push(r.annotation_source || 'Paper')
      csvRows.push(row.join(','))
    }
    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `${slug ?? 'datasets'}-${activeTab}.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  const displayRows = hasActiveFilters ? filteredRows : omicsRows

  // Literature tab content component

  return (
    <div className="h-screen flex flex-col bg-brand-bg">
      {/* Top bar */}
      <div className="bg-surface border-b border-border-light shrink-0">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <button onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-brand transition-colors mb-3">
            <ArrowLeft className="w-4 h-4" /> Back to Home
          </button>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-brand/10 to-brand-light/20 flex items-center justify-center">
              <HardDrive className="w-5 h-5 text-brand" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-text-primary">{tissueName}</h1>
              <p className="text-sm text-text-secondary">
                {rows.length > 0 ? [...new Set(rows.map((r) => r.disease))].join(' · ') : 'No datasets yet'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Omics type tabs + Tissue Workspace link */}
      <div className="border-b border-border-light bg-surface">
        <div className="max-w-7xl mx-auto px-6 flex gap-0 items-center">
          {OMICS_TABS.map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => setActiveTab(key)}
              className={`flex items-center gap-1.5 text-xs font-medium px-4 py-2.5 border-b-2 transition-colors ${
                activeTab === key
                  ? 'text-brand border-brand-gold'
                  : 'text-text-muted border-transparent hover:text-text-primary'
              }`}>
              <Icon className="w-3.5 h-3.5" /> {label}
            </button>
          ))}
          <button onClick={() => setActiveTab('literature')}
            className={`flex items-center gap-1.5 text-xs font-medium px-4 py-2.5 border-b-2 transition-colors ${
              activeTab === 'literature'
                ? 'text-brand border-brand-gold'
                : 'text-text-muted border-transparent hover:text-text-primary'
            }`}>
            <BookOpen className="w-3.5 h-3.5" /> Tissue Workspace
          </button>
        </div>
      </div>

      {/* Content: omics table + literature tab (display:none to preserve chat state) */}
      <div className={`flex-1 min-h-0 max-w-7xl mx-auto px-6 w-full ${activeTab === 'literature' ? '' : 'hidden'}`}>
        <LiteratureTab context={`${tissueName} — ${[...new Set(rows.map(r => r.disease))].join(', ')}`} />
      </div>
      <div className={`flex-1 min-h-0 overflow-y-auto max-w-7xl mx-auto px-6 py-4 w-full ${activeTab === 'literature' ? 'hidden' : ''}`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h2 className="text-[15px] font-semibold text-text-primary">Available Datasets</h2>
            {hasActiveFilters && (
              <button onClick={clearAllFilters} className="inline-flex items-center gap-1 text-xs text-brand hover:text-brand-dark">
                <XCircle className="w-3.5 h-3.5" /> Clear filters
              </button>
            )}
          </div>
          {omicsRows.length > 0 && (
            <button onClick={downloadCSV}
              className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-brand bg-surface border border-border-light hover:border-brand rounded-lg px-3 py-1.5 transition-colors">
              <Download className="w-3.5 h-3.5" /> CSV
            </button>
          )}
        </div>

        {loading ? (
          <div className="bg-surface rounded-xl shadow-card p-8 text-center">
            <Loader2 className="w-6 h-6 text-brand mx-auto mb-2 animate-spin" />
            <p className="text-sm text-text-muted">Scanning data directory...</p>
          </div>
        ) : omicsRows.length === 0 && activeTab !== 'single-cell' ? (
          <div className="bg-surface rounded-xl shadow-card p-12 text-center">
            <p className="text-text-secondary text-sm font-medium mb-2">
              No {OMICS_TABS.find(t => t.key === activeTab)?.label} data yet
            </p>
            <p className="text-xs text-text-muted">This omics type will be available in a future update.</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="bg-surface rounded-xl shadow-card p-8 text-center">
            <p className="text-text-secondary text-sm">
              No datasets found in <code className="text-xs bg-surface-muted px-1 rounded">{slug}/</code>
            </p>
          </div>
        ) : (
          <div className="bg-surface rounded-xl shadow-card overflow-x-auto">
            <table className="w-full text-sm min-w-[800px]">
              <thead>
                <tr className="bg-surface-raised border-b border-border-light">
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                    <FilterDropdown label="Species" values={getUniqueValues('species')}
                      selectedValues={filters['species']} onToggle={(v) => toggleFilter('species', v)}
                      onClear={() => clearFilter('species')} isActive={isFilterActive('species')} portal />
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                    <FilterDropdown label="Disease" values={getUniqueValues('disease')}
                      selectedValues={filters['disease']} onToggle={(v) => toggleFilter('disease', v)}
                      onClear={() => clearFilter('disease')} isActive={isFilterActive('disease')} portal />
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">PMID</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Size</th>
                  <th className="text-center py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Status</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Patient</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Sample</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">{isTabular ? 'Genes' : 'Cells'}</th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Group</th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">
                    <FilterDropdown label={isTabular ? 'Data Type' : 'Sample Type'} values={getUniqueValues(isTabular ? 'data_type' : 'tissue_obs')}
                      selectedValues={filters[isTabular ? 'data_type' : 'tissue_obs']} onToggle={(v) => toggleFilter(isTabular ? 'data_type' : 'tissue_obs', v)}
                      onClear={() => clearFilter(isTabular ? 'data_type' : 'tissue_obs')} isActive={isFilterActive(isTabular ? 'data_type' : 'tissue_obs')} portal />
                  </th>
                  {!isTabular && (
                    <th className="text-left py-3 px-4 text-xs font-semibold text-text-muted uppercase tracking-wider">Annotation Source</th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {displayRows.map((row, i) => (
                  <tr key={i} className="hover:bg-surface-muted/60 transition-colors">
                    <td className="py-3 px-4 text-sm text-text-primary">{row.species ?? 'Human'}</td>
                    <td className="py-3 px-4 text-sm font-medium text-text-primary">{row.disease}</td>
                    <td className="py-3 px-4">
                      <button onClick={() => {
                        if (row.status === 'ready') navigate(`/analysis/${slug}/${row.disease}/${row.pmid}`)
                      }} disabled={row.status !== 'ready'}
                        className={`inline-flex items-center gap-1 font-mono text-sm underline underline-offset-2 transition-colors ${
                          row.status === 'ready' ? 'text-brand hover:text-brand-dark' : 'text-text-muted cursor-not-allowed'
                        }`}>
                        {row.pmid} {row.status === 'ready' && <ExternalLink className="w-3 h-3" />}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-sm text-text-secondary text-right tabular-nums">
                      {row.size_mb && row.size_mb > 1000 ? `${(row.size_mb / 1024).toFixed(1)} GB` : `${row.size_mb} MB`}
                    </td>
                    <td className="py-3 px-4 text-center">
                      {row.status === 'ready' ? (
                        <span className="inline-flex items-center gap-1 text-xs text-success bg-success-bg px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full bg-success" /> Ready
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs text-warning bg-warning-bg px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse" /> Processing
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-sm text-text-primary text-right tabular-nums">{row.patient_count ?? '-'}</td>
                    <td className="py-3 px-4 text-sm text-text-primary text-right tabular-nums">{row.sample_count ?? '-'}</td>
                    <td className="py-3 px-4 text-sm text-text-primary text-right tabular-nums">{isTabular ? (row.n_vars ?? '-') : (row.celltype_count ?? '-')}</td>
                    <td className="py-2.5 px-4 text-xs text-text-secondary leading-snug break-words" title={row.group_dist}>{row.group_dist || '-'}</td>
                    <td className="py-3 px-4 text-sm text-text-secondary">{isTabular ? (row.data_type || '-') : (row.tissue_obs || '-')}</td>
                    {!isTabular && (
                      <td className="py-3 px-4 text-sm text-text-secondary">{row.annotation_source || 'Paper'}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-4 flex items-center gap-4 text-xs text-text-muted">
          <span>{rows.length} dataset(s)</span>
          {rows.some((r) => r.status !== 'ready') && (
            <span className="text-warning flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse" /> Processing...
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
