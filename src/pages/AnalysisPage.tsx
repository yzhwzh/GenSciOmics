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
} from '../components/analysis'
import type { AnalysisInfo, UmapData } from '../api/types'

export default function AnalysisPage() {
  const { tissue, disease, pmid } = useParams()
  const navigate = useNavigate()

  // Dataset file path
  const [realPath, setRealPath] = useState('')
  const [error, setError] = useState('')

  // Data states
  const [info, setInfo] = useState<AnalysisInfo | null>(null)
  const [infoLoading, setInfoLoading] = useState(true)
  const [umapData, setUmapData] = useState<UmapData | null>(null)
  const [umapLoading, setUmapLoading] = useState(false)

  // Controls
  const [colorBy, setColorBy] = useState('CellType')
  const [geneName, setGeneName] = useState(() => {
    try { return sessionStorage.getItem('gensci_gene_name') ?? '' } catch { return '' }
  })
  const [geneName2, setGeneName2] = useState(() => {
    try { return sessionStorage.getItem('gensci_gene_name2') ?? '' } catch { return '' }
  })
  const [umapPalette, setUmapPalette] = useState('default')
  const [activeTab, setActiveTab] = useState(() => {
    try {
      const saved = sessionStorage.getItem('gensci_active_tab')
      return saved ? parseInt(saved, 10) : 0
    } catch { return 0 }
  })

  // Persist active tab to sessionStorage (survives page refresh)
  useEffect(() => {
    try { sessionStorage.setItem('gensci_active_tab', String(activeTab)) } catch { /* ignore */ }
  }, [activeTab])

  // Persist gene names across page refreshes
  useEffect(() => {
    try { sessionStorage.setItem('gensci_gene_name', geneName) } catch { /* ignore */ }
  }, [geneName])
  useEffect(() => {
    try { sessionStorage.setItem('gensci_gene_name2', geneName2) } catch { /* ignore */ }
  }, [geneName2])

  const TABS = [
    { label: 'Study Info', icon: FileText, short: 'Study Info' },
    { label: 'UMAP', icon: ScatterChart, short: 'UMAP' },
    { label: 'Expression per Sample x Cell Type', icon: Box, short: 'Per-Sample BoxPlot' },
    { label: 'Expression by Cell Type', icon: BarChart3, short: 'Aggregate BarPlot' },
    { label: 'Free Analysis', icon: Brain, short: 'Free Analysis' },
  ]

  // Load dataset path
  useEffect(() => {
    if (!tissue || !disease || !pmid) return
    findDataset(tissue, disease, pmid).then((ds) => {
      if (ds?.real_path) setRealPath(ds.real_path)
      else setError('Dataset not found in scanned directories')
    })
  }, [tissue, disease, pmid])

  // Fetch analysis info
  useEffect(() => {
    if (!realPath || !pmid) return
    setInfoLoading(true)
    fetchAnalysisInfo(pmid, realPath)
      .then((d) => setInfo(d))
      .catch(() => setError('Failed to load analysis info'))
      .finally(() => setInfoLoading(false))
  }, [realPath, pmid])

  // Fetch UMAP data
  const fetchUmap = useCallback(() => {
    if (!realPath) return
    setUmapLoading(true)
    fetchUmapData(realPath, colorBy, 50000, colorBy === 'Gene' ? geneName : undefined, umapPalette, colorBy === 'Gene' ? geneName2 : undefined)
      .then((d) => setUmapData(d as UmapData))
      .catch(() => setUmapData(null))
      .finally(() => setUmapLoading(false))
  }, [realPath, colorBy, geneName, geneName2, umapPalette])

  useEffect(() => { if (realPath) fetchUmap() }, [fetchUmap])

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 text-sm mb-3">{error}</p>
          <button onClick={() => navigate(-1)} className="text-sm text-blue-600 hover:underline">Go Back</button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-gray-50 flex flex-col overflow-hidden">
      {/* Top Bar */}
      <div className="bg-white border-b border-gray-200 shrink-0">
        <div className="max-w-full mx-auto px-4 py-1.5">
          <div className="flex items-center gap-2 min-w-0">
            <button onClick={() => navigate(`/tissue/${tissue}`)}
              className="flex items-center gap-1 text-sm text-gray-500 hover:text-blue-600 transition-colors shrink-0">
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
            <div className="h-4 w-px bg-gray-200 shrink-0" />
            <span className="text-sm font-semibold text-gray-800 truncate">{disease}</span>
            <span className="text-[11px] text-gray-400 font-mono shrink-0">PMID:{pmid}</span>
            {info?.abstract?.title && (
              <span className="text-[11px] text-gray-500 truncate hidden md:inline max-w-[300px]">{info.abstract.title}</span>
            )}
          </div>
        </div>
      </div>

      {/* Body: Sidebar Tabs + Content */}
      <div className="flex-1 flex gap-3 p-3 min-h-0">
        {/* Sidebar */}
        <div className="flex flex-col gap-1 w-[120px] shrink-0 pt-1">
          {TABS.map((tab, i) => (
            <button key={i} onClick={() => setActiveTab(i)}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-lg text-left transition-all text-xs font-medium ${
                activeTab === i
                  ? 'bg-brand text-white shadow-sm'
                  : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'
              }`}>
              <tab.icon className="w-4 h-4 shrink-0" />
              <span className="leading-tight">{tab.short ?? tab.label}</span>
            </button>
          ))}
        </div>

        {/* Content — only Free Analysis is kept mounted (display:none) to preserve chat state;
            other tabs use conditional rendering to avoid ResizeObserver/stream issues */}
        <div className="flex-1 min-w-0">
          {activeTab === 0 && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm h-full flex flex-col overflow-hidden">
              <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 pt-2.5 pb-0 shrink-0">Study Info</div>
              <div className="flex-1 min-h-0"><InfoPanel info={info} loading={infoLoading} /></div>
            </div>
          )}
          {activeTab === 1 && (
            <UmapTabContent realPath={realPath} umapData={umapData} umapLoading={umapLoading} colorBy={colorBy} onColorByChange={setColorBy} geneName={geneName} onGeneNameChange={setGeneName} geneName2={geneName2} onGeneName2Change={setGeneName2} palette={umapPalette} onPaletteChange={setUmapPalette} />
          )}
          {activeTab === 2 && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm h-full flex flex-col overflow-hidden">
              <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 pt-2.5 pb-0 shrink-0">Gene Expression per Sample x Cell Type</div>
              <div className="flex-1 min-h-0">
                {realPath ? <BoxPlotContainer realPath={realPath} /> : <div className="text-sm text-gray-400 p-4">Loading dataset...</div>}
              </div>
            </div>
          )}
          {activeTab === 3 && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm h-full flex flex-col overflow-hidden">
              <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 pt-2.5 pb-0 shrink-0">Expression by Cell Type (Aggregate)</div>
              <div className="flex-1 min-h-0">
                {realPath ? <ExpressionChartContainer realPath={realPath} /> : <div className="text-sm text-gray-400 p-4">Loading dataset...</div>}
              </div>
            </div>
          )}
          {/* Free Analysis — display:none to keep chat state alive across tab switches */}
          <div className="h-full" style={{ display: activeTab === 4 ? 'block' : 'none' }}>
            <FreeAnalysisTab realPath={realPath} />
          </div>
        </div>
      </div>
    </div>
  )
}
