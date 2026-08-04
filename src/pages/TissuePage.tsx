import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Download, ExternalLink, HardDrive, Loader2, XCircle, BookOpen } from 'lucide-react'
import { fetchDatasets } from '../api/datasets'
import { ORGANS } from '../data/mockData'
import { useTableFilter } from '../hooks/useTableFilter'
import FilterDropdown from '../components/FilterDropdown'
import { LiteratureTab } from '../components/analysis'
import type { DatasetInfo } from '../api/types'

export default function TissuePage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const [rows, setRows] = useState<DatasetInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'datasets' | 'literature'>('datasets')
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

  const downloadCSV = () => {
    const headers = ['Disease', 'PMID', 'File Size', 'Status', 'Patient', 'Sample', 'CellType', 'Group (samples/cells)', 'Sample Type']
    const csvRows = [headers.join(',')]
    for (const r of rows) {
      csvRows.push([
        `"${r.disease}"`,
        r.pmid,
        r.size_mb && r.size_mb > 1000 ? `${(r.size_mb / 1024).toFixed(1)} GB` : `${r.size_mb} MB`,
        r.status,
        r.patient_count ?? '-',
        r.sample_count ?? '-',
        r.celltype_count ?? '-',
        `"${r.group_dist || '-'}"`,
        `"${r.tissue_obs || '-'}"`,
      ].join(','))
    }
    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${slug ?? 'datasets'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  useEffect(() => {
    if (!slug || loading) return
    const hasPending = rows.some((r) => r.status !== 'ready')
    if (!hasPending) return

    const interval = setInterval(() => {
      fetchDatasets(slug)
        .then((data) => { if (Array.isArray(data)) setRows(data) })
        .catch(() => {})
    }, 5000)

    return () => clearInterval(interval)
  }, [slug, loading, rows])

  return (
    <div className="h-screen flex flex-col bg-gray-50/50">
      {/* Top bar */}
      <div className="bg-white border-b border-gray-200 shrink-0">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-blue-600 transition-colors mb-3"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Home
          </button>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-100 to-blue-200 flex items-center justify-center">
              <HardDrive className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">{tissueName}</h1>
              <p className="text-sm text-gray-500">
                {rows.length > 0
                  ? [...new Set(rows.map((r) => r.disease))].join(' · ')
                  : `No datasets yet`}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="border-b border-gray-200 bg-white">
        <div className="max-w-7xl mx-auto px-6 flex gap-0">
          <button onClick={() => setActiveTab('datasets')}
            className={`flex items-center gap-1.5 text-[11px] font-medium px-4 py-2 border-b-2 transition-colors ${
              activeTab === 'datasets' ? 'text-blue-600 border-blue-500' : 'text-gray-400 border-transparent hover:text-gray-600'
            }`}>
            <HardDrive className="w-3.5 h-3.5" />
            Datasets
          </button>
          <button onClick={() => setActiveTab('literature')}
            className={`flex items-center gap-1.5 text-[11px] font-medium px-4 py-2 border-b-2 transition-colors ${
              activeTab === 'literature' ? 'text-emerald-600 border-emerald-500' : 'text-gray-400 border-transparent hover:text-gray-600'
            }`}>
            <BookOpen className="w-3.5 h-3.5" />
            Tissue Workspace
          </button>
        </div>
      </div>

      {/* Content — both tabs always mounted, hidden via CSS to preserve state */}
      <div className={`flex-1 min-h-0 px-6 py-4 max-w-7xl mx-auto w-full ${activeTab !== 'literature' ? 'hidden' : ''}`}>
        <LiteratureTab context={`${tissueName} — ${[...new Set(rows.map(r => r.disease))].join(', ')}`} />
      </div>

      <div className={`max-w-7xl mx-auto px-6 py-6 overflow-y-auto ${activeTab !== 'datasets' ? 'hidden' : ''}`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold text-gray-900">
              Available Datasets
            </h2>
            {hasActiveFilters && (
              <div className="flex items-center gap-2">
                <button onClick={clearAllFilters}
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800">
                  <XCircle className="w-3.5 h-3.5" />
                  Clear filters
                </button>
                <span className="text-xs text-gray-400">
                  {filteredRows.length} / {rows.length} rows
                </span>
              </div>
            )}
          </div>
          {rows.length > 0 && (
            <button
              onClick={downloadCSV}
              className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-blue-600 bg-white border border-gray-200 hover:border-blue-300 rounded-lg px-3 py-1.5 transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              Download CSV
            </button>
          )}
        </div>

        {loading ? (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-8 text-center">
            <Loader2 className="w-6 h-6 text-blue-500 mx-auto mb-2 animate-spin" />
            <p className="text-sm text-gray-400">Scanning data directory...</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-8 text-center">
            <p className="text-gray-500 text-sm">
              No datasets found in <code className="text-xs bg-gray-100 px-1 rounded">{slug}/</code>
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Add .h5ad files to the directory — the system will detect them automatically.
            </p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-x-auto">
            <table className="w-full text-sm min-w-[800px]">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">
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
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">
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
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">PMID</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">File Size</th>
                  <th className="text-center py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Status</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">Patient</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">Sample</th>
                  <th className="text-right py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">CellType</th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">Group <span className="font-normal text-gray-400">(samples/cells)</span></th>
                  <th className="text-left py-3 px-4 text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
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
              <tbody className="divide-y divide-gray-100">
                {(hasActiveFilters ? filteredRows : rows).map((row, i) => (
                  <tr key={i} className="hover:bg-blue-50/40 transition-colors">
                    <td className="py-3 px-4 text-sm text-gray-700">
                      {row.species ?? 'Human'}
                    </td>
                    <td className="py-3 px-4 text-sm font-medium text-gray-800">
                      {row.disease}
                    </td>
                    <td className="py-3 px-4">
                      <button
                        onClick={() => {
                          if (row.status === 'ready') {
                            navigate(`/analysis/${slug}/${row.disease}/${row.pmid}`)
                          }
                        }}
                        disabled={row.status !== 'ready'}
                        className={`inline-flex items-center gap-1 font-mono text-sm underline underline-offset-2 transition-colors ${
                          row.status === 'ready'
                            ? 'text-blue-600 hover:text-blue-800 hover:no-underline cursor-pointer'
                            : 'text-gray-300 cursor-not-allowed'
                        }`}
                      >
                        {row.pmid}
                        {row.status === 'ready' && <ExternalLink className="w-3 h-3" />}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-sm text-gray-600 text-right tabular-nums">
                      {row.size_mb && row.size_mb > 1000
                        ? `${(row.size_mb / 1024).toFixed(1)} GB`
                        : `${row.size_mb} MB`}
                    </td>
                    <td className="py-3 px-4 text-center">
                      {row.status === 'ready' ? (
                        <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                          Ready
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs text-yellow-700 bg-yellow-50 px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse" />
                          Processing
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-sm text-gray-700 text-right tabular-nums">
                      {row.patient_count ?? '-'}
                    </td>
                    <td className="py-3 px-4 text-sm text-gray-700 text-right tabular-nums">
                      {row.sample_count ?? '-'}
                    </td>
                    <td className="py-3 px-4 text-sm text-gray-700 text-right tabular-nums">
                      {row.celltype_count ?? '-'}
                    </td>
                    <td className="py-2.5 px-4 text-xs text-gray-600 leading-snug break-words" title={row.group_dist}>
                      {row.group_dist || '-'}
                    </td>
                    <td className="py-3 px-4 text-sm text-gray-600">
                      {row.tissue_obs || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-4 flex items-center gap-4 text-xs text-gray-400">
          <span>{rows.length} dataset(s) · Auto-detected from filesystem</span>
          {rows.some((r) => r.status !== 'ready') && (
            <span className="text-yellow-600 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse" />
              Some files are being processed
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
