import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Download, ExternalLink, HardDrive, Loader2, XCircle, BookOpen, Dna, FlaskConical, Beaker, Microscope, AlertTriangle, RefreshCw } from 'lucide-react'
import { fetchDatasets, fetchDatasetsFresh } from '../api/datasets'
import { ORGANS } from '../data/mockData'
import { useTableFilter } from '../hooks/useTableFilter'
import FilterDropdown from '../components/FilterDropdown'
import { LiteratureTab } from '../components/analysis'
import type { DatasetInfo } from '../api/types'

type OmicsTab = 'single-cell' | 'bulk-rna' | 'proteomics' | 'metabolomics' | 'literature'

// B30: a row whose .h5ad could not be read comes back with all-zero counts. 0 is
// a measurement, so printing it asserts something we do not know — show "—" and
// say why. The backend retries every scan, so this clears on its own.
const READ_FAILED_HINT =
  'Could not read this data file — it may be mid-edit or corrupt. Retrying automatically.'
const UNREADABLE = <span className="text-text-muted" title={READ_FAILED_HINT}>—</span>

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
  const [loadError, setLoadError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<OmicsTab>(() => {
    try {
      const v = sessionStorage.getItem('gensci_tissue_tab') as OmicsTab | null
      return v && OMICS_TABS.some((t) => t.key === v) ? v : 'single-cell'
    } catch { return 'single-cell' }
  })
  const {
    filteredRows, getUniqueValues, toggleFilter, clearFilter, clearAllFilters, isFilterActive, filters,
  } = useTableFilter(rows)

  // Persist the active omics tab so a refresh doesn't bounce back to Single Cell.
  useEffect(() => {
    try { sessionStorage.setItem('gensci_tissue_tab', activeTab) } catch { /* ignore */ }
  }, [activeTab])

  const organ = ORGANS.find((o) => o.slug === slug)
  const tissueName = organ?.label ?? slug ?? 'Unknown'
  const hasActiveFilters = Object.values(filters).some(s => s.size > 0)

  // Holds the message, not a boolean: a 60s timeout, an HTTP 502 and a malformed
  // body are otherwise indistinguishable in the UI and lost entirely.
  const [pollError, setPollError] = useState<string | null>(null)
  // Retry re-runs the load effect below rather than re-issuing the request itself.
  const [attempt, setAttempt] = useState(0)

  // Every request is issued from inside an effect, including the one Retry
  // triggers (`attempt` is its only input). That is deliberate: the cleanup
  // below is the only thing that can cancel a request, and React discards the
  // return value of an onClick handler — so a Retry that called a loader
  // directly would leave its own request uncancellable, and navigating away
  // while it was in flight would let it repaint the tissue you moved to.
  useEffect(() => {
    if (!slug) return
    let cancelled = false
    setLoading(true)
    fetchDatasets(slug)
      .then(async (data) => {
        let loaded = Array.isArray(data) ? data : []
        // A successful-but-empty answer is not yet a fact about the data. The
        // backend serves [] for every list request until its initial filesystem
        // scan finishes, so an empty list just after a restart means "not ready
        // yet" at least as often as it means "this tissue is empty" — and
        // rendering it as "No datasets found" is the very claim B29 is about.
        // One fresh re-check separates the two; only a second empty answer is
        // rendered as a statement about the data.
        if (loaded.length === 0) {
          // A failed re-check is deliberately not an error state: the first
          // request succeeded, so the empty list stands as the best answer we
          // actually have, and the user keeps the Refresh button below.
          // try/catch rather than .catch() so a synchronous throw is contained
          // too — otherwise a fault in the re-check would reject this handler
          // and turn a successful load into a load error.
          try {
            const rechecked = await fetchDatasetsFresh(slug)
            if (Array.isArray(rechecked)) loaded = rechecked
          } catch { /* keep the empty list */ }
          if (cancelled) return
        }
        if (cancelled) return
        setRows(loaded)
        setLoadError(null)
        // This response is authoritative, so any earlier poll failure is moot.
        // Without this, a poll that failed once would keep claiming "refresh
        // failing" after a Retry had already fixed it.
        setPollError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setRows([])
        // Never an empty string: `loadError` doubles as the "did it fail?"
        // discriminant below, so '' would fall through and re-render the
        // original "No datasets found" claim the fix exists to prevent.
        setLoadError(err instanceof Error && err.message ? err.message : 'Request failed')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [slug, attempt])

  // Polls only while some dataset is still being processed. Deliberately not
  // cachedFetch: with the default TTL every tick would return the identical
  // array for five minutes, and setRows(sameRef) bails out of re-rendering, so
  // the interval would never be recreated and the badge would never update.
  useEffect(() => {
    if (!slug || loading) return
    if (!rows.some((r) => r.status !== 'ready')) return
    let cancelled = false
    const interval = setInterval(() => {
      fetchDatasetsFresh(slug)
        .then((data) => {
          if (cancelled || !Array.isArray(data)) return
          setRows(data)
          setPollError(null)
        })
        // Surfaced rather than swallowed: if the backend dies mid-processing the
        // page would otherwise pulse "Processing..." forever with no hint that
        // the requests are failing.
        .catch((err: unknown) => {
          if (cancelled) return
          setPollError(err instanceof Error && err.message ? err.message : 'Request failed')
        })
    }, 5000)
    return () => { cancelled = true; clearInterval(interval) }
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
      // Same rule as the table: a failed read has no counts to report, and a
      // literal 0 survives into whatever downstream analysis reads this CSV.
      const unreadable = r.status === 'error'
      const row = [
        r.species ?? 'Human', `"${r.disease}"`, r.pmid,
        r.size_mb && r.size_mb > 1000 ? `${(r.size_mb / 1024).toFixed(1)} GB` : `${r.size_mb} MB`,
        r.status,
        unreadable ? '-' : (r.patient_count ?? '-'),
        unreadable ? '-' : (r.sample_count ?? '-'),
        unreadable ? '-' : (isTabular ? (r.n_vars ?? '-') : (r.celltype_count ?? '-')),
        `"${r.group_dist || '-'}"`,
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
  const diseases = [...new Set(rows.map((r) => r.disease))]
  // 'error' is a read failure the backend will retry on its next scan (~30s);
  // 'importing' (and any future pending state) is genuine in-progress work.
  // Keeping them apart matters: the footer used to call every non-ready row
  // "Processing...", which is a false claim about an unreadable file.
  //
  // Counted over displayRows, not rows: the footer sits directly under the
  // table and reads as a statement about it. Deriving from `rows` let a row the
  // reader cannot see — another omics tab, or one filtered out — produce a
  // warning with no visible referent. The poll below still watches all `rows`,
  // so a hidden failure keeps healing; it just stops shouting from off-screen.
  const errorRows = displayRows.filter((r) => r.status === 'error')
  const processingRows = displayRows.filter((r) => r.status !== 'ready' && r.status !== 'error')

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
                {loadError
                  ? 'Dataset list unavailable'
                  : diseases.length > 0 ? diseases.join(' · ') : 'No datasets yet'}
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
        {/* The context string is fed to the LLM. Leaving it as "Kidney — " on a
            failed load would read as "this tissue has no diseases", which is the
            same false absence claim the empty state was fixed to stop making. */}
        <LiteratureTab context={`${tissueName} — ${
          loadError ? 'dataset list currently unavailable' : diseases.join(', ') || 'no datasets'
        }`} />
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
        ) : loadError ? (
          <div className="bg-surface rounded-xl shadow-card p-12 text-center">
            <AlertTriangle className="w-6 h-6 text-warning mx-auto mb-3" />
            <p className="text-text-secondary text-sm font-medium mb-1">Failed to load datasets</p>
            <p className="text-xs text-text-muted mb-4">
              The server did not respond ({loadError}). This says nothing about whether
              data exists — the request itself failed.
            </p>
            <button onClick={() => setAttempt((n) => n + 1)}
              className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-brand bg-surface border border-border-light hover:border-brand rounded-lg px-3 py-1.5 transition-colors">
              <RefreshCw className="w-3.5 h-3.5" /> Retry
            </button>
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
            <p className="text-text-secondary text-sm mb-4">
              No datasets found in <code className="text-xs bg-surface-muted px-1 rounded">{slug}/</code>
            </p>
            {/* The answer above is only as fresh as the last request. Datasets
                are added by re-linking files under an already-open page, so
                without this the reader has no way to re-ask short of a reload. */}
            <button onClick={() => setAttempt((n) => n + 1)}
              className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-brand bg-surface border border-border-light hover:border-brand rounded-lg px-3 py-1.5 transition-colors">
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </button>
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
                      ) : row.status === 'error' ? (
                        <span className="inline-flex items-center gap-1 text-xs text-error bg-error-bg px-2 py-0.5 rounded-full" title={READ_FAILED_HINT}>
                          <AlertTriangle className="w-3 h-3" /> Read failed
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs text-warning bg-warning-bg px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse" /> Processing
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-sm text-text-primary text-right tabular-nums">{row.status === 'error' ? UNREADABLE : (row.patient_count ?? '-')}</td>
                    <td className="py-3 px-4 text-sm text-text-primary text-right tabular-nums">{row.status === 'error' ? UNREADABLE : (row.sample_count ?? '-')}</td>
                    <td className="py-3 px-4 text-sm text-text-primary text-right tabular-nums">{row.status === 'error' ? UNREADABLE : (isTabular ? (row.n_vars ?? '-') : (row.celltype_count ?? '-'))}</td>
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

        {/* "0 dataset(s)" would read as a fact about the data; on a failed load
            we don't know the count at all, so the tally is withheld. */}
        <div className={`mt-4 flex items-center gap-4 text-xs text-text-muted ${loadError ? 'invisible' : ''}`}>
          <span>{rows.length} dataset(s)</span>
          {(errorRows.length > 0 || processingRows.length > 0 || pollError !== null) && (
            <>
              {errorRows.length > 0 && (
                <span className="text-error flex items-center gap-1" title={READ_FAILED_HINT}>
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {errorRows.length} dataset(s) could not be read — retrying automatically
                </span>
              )}
              {processingRows.length > 0 && !pollError && (
                <span className="text-warning flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse" /> Processing...
                </span>
              )}
              {pollError && (
                <span className="text-warning flex items-center gap-1" title={pollError}>
                  <AlertTriangle className="w-3.5 h-3.5" /> Status refresh failing ({pollError}) — counts may be stale
                </span>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
