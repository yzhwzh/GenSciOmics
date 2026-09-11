import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, FileText, ScatterChart, Box, BarChart3, Brain } from 'lucide-react'
import { findDataset } from '../api/datasets'
import { fetchAnalysisInfo, fetchUmapData } from '../api/analysis'
import {
  InfoPanel,
  UmapTabContent,
  BoxPlotContainer,
  ExpressionChartContainer,
  FreeAnalysisTab,
  BulkAnalysisTab,
} from '../components/analysis'
import type { AnalysisInfo, UmapData } from '../api/types'

// Shown when the scanner could not read the file behind this dataset. Both
// messages name the recovery, because both recover on their own: the scanner
// re-reads every 30s and the Retry button below re-runs the lookup.
const READ_FAILED =
  'Could not read this data file — it may be mid-edit or corrupt. The backend re-scans every 30 seconds; try again in a moment.'
const IMPORTING = 'This dataset is still being imported. Try again in a moment.'

export default function AnalysisPage() {
  const { tissue, disease, pmid } = useParams()
  const navigate = useNavigate()

  const [realPath, setRealPath] = useState('')
  const [omicsType, setOmicsType] = useState('')
  const [markerMajor, setMarkerMajor] = useState<Record<string, string[]> | null>(null)
  const [error, setError] = useState('')
  // A failed read heals on its own once the scanner re-reads the file, so the
  // error screen has to be re-runnable rather than a dead end.
  const [canRetry, setCanRetry] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [info, setInfo] = useState<AnalysisInfo | null>(null)
  const [infoLoading, setInfoLoading] = useState(true)
  const [umapData, setUmapData] = useState<UmapData | null>(null)
  const [umapLoading, setUmapLoading] = useState(false)

  const [colorBy, setColorBy] = useState('CellType')
  const [geneName, setGeneName] = useState(() => {
    try { return sessionStorage.getItem('gensci_gene_name') ?? '' } catch { return '' }
  })
  const [geneName2, setGeneName2] = useState(() => {
    try { return sessionStorage.getItem('gensci_gene_name2') ?? '' } catch { return '' }
  })
  const [umapPalette, setUmapPalette] = useState('default')
  const [activeTab, setActiveTab] = useState(() => {
    try { const s = sessionStorage.getItem('gensci_active_tab'); return s ? parseInt(s, 10) : 0 } catch { return 0 }
  })

  useEffect(() => { try { sessionStorage.setItem('gensci_active_tab', String(activeTab)) } catch { /* ignore */ } }, [activeTab])
  useEffect(() => { try { sessionStorage.setItem('gensci_gene_name', geneName) } catch { /* ignore */ } }, [geneName])
  useEffect(() => { try { sessionStorage.setItem('gensci_gene_name2', geneName2) } catch { /* ignore */ } }, [geneName2])

  const isBulk = omicsType === 'BulkRNA'
  const isProtein = omicsType === 'Protein'
  const isTabular = isBulk || isProtein
  const TABS = isTabular
    ? [
        { label: 'Study Info', icon: FileText },
        { label: 'Expression & DE', icon: BarChart3 },
        { label: 'Free Analysis', icon: Brain },
      ]
    : [
        { label: 'Study Info', icon: FileText },
        { label: 'UMAP', icon: ScatterChart },
        { label: 'BoxPlot', icon: Box },
        { label: 'BarPlot', icon: BarChart3 },
        { label: 'Free Analysis', icon: Brain },
      ]

  // Re-runs the lookup without unmounting. `error` is deliberately not cleared
  // here: the error screen stays up while the retry is in flight, so a failed
  // retry is a no-op on screen instead of a flash of an empty analysis page.
  const retry = useCallback(() => setAttempt((a) => a + 1), [])

  useEffect(() => {
    if (!tissue || !disease || !pmid) return
    findDataset(tissue, disease, pmid).then((ds) => {
      // The tissue table disables the link for anything not 'ready', but a
      // hand-typed URL, a bookmark or the back button still lands here — and
      // this used to take real_path and load regardless. Every request below
      // (analysis-info, UMAP, plots) would then read a file the scanner has
      // already said it cannot read, and present the resulting zeros as data.
      // The refusal mirrors the link's exactly; if they ever disagree, one of
      // the two is wrong.
      if (ds && ds.status !== 'ready') {
        setError(ds.status === 'error' ? READ_FAILED : IMPORTING)
        setCanRetry(true)
        return
      }
      if (ds?.real_path) {
        setError('')
        setCanRetry(false)
        setRealPath(ds.real_path)
        setOmicsType(ds.omics_type ?? '')
        setMarkerMajor(ds.marker_major ?? null)
      } else {
        setError('Dataset not found')
        setCanRetry(false)
      }
    })
  }, [tissue, disease, pmid, attempt])

  // Clamp activeTab when switching between omics types (tabular has only 3 tabs)
  useEffect(() => {
    if (isTabular && activeTab > 2) setActiveTab(0)
  }, [isTabular, activeTab])

  useEffect(() => {
    if (!realPath || !pmid) return
    let cancelled = false
    setInfoLoading(true)
    fetchAnalysisInfo(pmid, realPath)
      .then((data) => { if (!cancelled) setInfo(data) })
      .catch(() => { if (!cancelled) setError('Failed to load info') })
      .finally(() => { if (!cancelled) setInfoLoading(false) })
    return () => { cancelled = true }
  }, [realPath, pmid])

  const fetchUmap = useCallback(() => {
    if (!realPath) return
    setUmapLoading(true)
    fetchUmapData(realPath, colorBy, 50000, colorBy === 'Gene' ? geneName : undefined, umapPalette, colorBy === 'Gene' ? geneName2 : undefined)
      .then((d) => setUmapData(d as UmapData)).catch(() => setUmapData(null)).finally(() => setUmapLoading(false))
  }, [realPath, colorBy, geneName, geneName2, umapPalette])

  useEffect(() => {
    if (!realPath || activeTab !== 1) return
    let cancelled = false
    fetchUmap()
    return () => { cancelled = true }
  }, [fetchUmap, activeTab])

  if (error) {
    return (
      <div className="min-h-screen bg-brand-bg flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <p className="text-error text-sm mb-3">{error}</p>
          <div className="flex items-center justify-center gap-5">
            {canRetry && (
              <button onClick={retry} className="text-sm text-brand hover:underline">Retry</button>
            )}
            <button onClick={() => navigate(-1)} className="text-sm text-brand hover:underline">Go Back</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-brand-bg flex flex-col overflow-hidden">
      {/* Top Bar */}
      <div className="bg-surface border-b border-border-light shrink-0">
        <div className="max-w-full mx-auto px-4 py-1.5 flex items-center gap-2 min-w-0">
          <button onClick={() => navigate(`/tissue/${tissue}`)}
            className="flex items-center gap-1 text-sm text-text-secondary hover:text-brand transition-colors shrink-0">
            <ArrowLeft className="w-4 h-4" /> Back
          </button>
          <div className="h-4 w-px bg-border-light shrink-0" />
          <span className="text-sm font-semibold text-text-primary truncate">{disease}</span>
          <span className="text-[11px] text-text-muted font-mono shrink-0">PMID:{pmid}</span>
          {info?.abstract?.title && (
            <span className="text-[11px] text-text-secondary truncate hidden md:inline max-w-[300px]">{info.abstract.title}</span>
          )}
        </div>
      </div>

      {/* Horizontal Tab Bar */}
      <div className="flex gap-0 bg-surface border-b border-border-light px-4 shrink-0">
        {TABS.map((tab, i) => (
          <button key={i} onClick={() => setActiveTab(i)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all cursor-pointer ${
              activeTab === i
                ? 'text-brand border-brand-gold'
                : 'text-text-secondary border-transparent hover:text-text-primary hover:bg-surface-muted'
            }`}>
            <tab.icon className="w-4 h-4 shrink-0" />
            <span className="whitespace-nowrap">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Content — only active Tab mounted to avoid I/O storm */}
      <div className="flex-1 min-h-0">
        {activeTab === 0 && (
          <div className="h-full flex-col bg-surface rounded-xl m-3 shadow-card overflow-hidden flex">
            <div className="text-xs font-semibold text-text-muted uppercase tracking-wider px-4 pt-2.5 pb-0 shrink-0">Study Info</div>
            <div className="flex-1 min-h-0"><InfoPanel info={info} loading={infoLoading} isBulk={isTabular} /></div>
          </div>
        )}
        {isTabular && activeTab === 1 && (
          <div className="h-full flex-col bg-surface rounded-xl m-3 shadow-card overflow-hidden flex">
            <div className="text-xs font-semibold text-text-muted uppercase tracking-wider px-4 pt-2.5 pb-0 shrink-0">Expression & Differential Expression</div>
            <div className="flex-1 min-h-0">
              {realPath ? <BulkAnalysisTab realPath={realPath} omicsType={omicsType} /> : <div className="text-sm text-text-muted p-4">Loading dataset...</div>}
            </div>
          </div>
        )}
        {!isTabular && activeTab === 1 && (
          <div className="h-full p-3">
            <UmapTabContent realPath={realPath} umapData={umapData} umapLoading={umapLoading} colorBy={colorBy} onColorByChange={setColorBy} geneName={geneName} onGeneNameChange={setGeneName} geneName2={geneName2} onGeneName2Change={setGeneName2} palette={umapPalette} onPaletteChange={setUmapPalette} markerMajor={markerMajor} />
          </div>
        )}
        {!isTabular && activeTab === 2 && (
          <div className="h-full flex-col bg-surface rounded-xl m-3 shadow-card overflow-hidden flex">
            <div className="text-xs font-semibold text-text-muted uppercase tracking-wider px-4 pt-2.5 pb-0 shrink-0">Expression per Sample × Cell Type</div>
            <div className="flex-1 min-h-0">
              {realPath ? <BoxPlotContainer realPath={realPath} /> : <div className="text-sm text-text-muted p-4">Loading dataset...</div>}
            </div>
          </div>
        )}
        {!isTabular && activeTab === 3 && (
          <div className="h-full flex-col bg-surface rounded-xl m-3 shadow-card overflow-hidden flex">
            <div className="text-xs font-semibold text-text-muted uppercase tracking-wider px-4 pt-2.5 pb-0 shrink-0">Expression by Cell Type (Aggregate)</div>
            <div className="flex-1 min-h-0">
              {realPath ? <ExpressionChartContainer realPath={realPath} /> : <div className="text-sm text-text-muted p-4">Loading dataset...</div>}
            </div>
          </div>
        )}
        {/* Free Analysis — display:none to keep chat state alive across tab switches */}
        {isTabular && (
          <div className="h-full p-3" style={{ display: activeTab === 2 ? 'block' : 'none' }}>
            <FreeAnalysisTab realPath={realPath} omicsType={omicsType} />
          </div>
        )}
        {!isTabular && (
          <div className="h-full p-3" style={{ display: activeTab === 4 ? 'block' : 'none' }}>
            <FreeAnalysisTab realPath={realPath} />
          </div>
        )}
      </div>
    </div>
  )
}
