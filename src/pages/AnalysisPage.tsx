import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, FileText, ScatterChart, Box, BarChart3, Brain } from 'lucide-react'
import { findDataset } from '../api/datasets'
import { fetchAnalysisInfo, fetchAbstract, fetchUmapData } from '../api/analysis'
import {
  InfoPanel,
  UmapTabContent,
  BoxPlotContainer,
  ExpressionChartContainer,
  FreeAnalysisTab,
  BulkAnalysisTab,
} from '../components/analysis'
import { useStoredGene, UMAP_GENE_KEY, UMAP_GENE2_KEY } from '../components/analysis/useStoredGene'
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
  // 与 infoLoading 分开：stats 先到就先渲染，摘要那一块自己转自己的圈。
  // 摘要这次取败了。注意**没有** abstractLoading 状态：转圈与否由数据推导
  // （见 InfoPanel），effect 里 set 的标志在 effect 跑起来之前仍是 false，
  // 会让每一轮冷加载先闪一帧「Abstract not available」。
  const [abstractError, setAbstractError] = useState(false)
  const [abstractNonce, setAbstractNonce] = useState(0)
  const retryAbstract = useCallback(() => setAbstractNonce((n) => n + 1), [])
  const [umapData, setUmapData] = useState<UmapData | null>(null)
  const [umapLoading, setUmapLoading] = useState(false)

  const [colorBy, setColorBy] = useState('CellType')
  // Both start out empty because realPath is not known yet — an empty gene is
  // the "nothing chosen" state here, not a dataset's remembered pick. The hook
  // reads the real value once the path arrives, and will not write before then.
  // See useStoredGene.ts / BUG_LOG B34.
  const [geneName, setGeneName] = useStoredGene(UMAP_GENE_KEY, realPath, '')
  const [geneName2, setGeneName2] = useStoredGene(UMAP_GENE2_KEY, realPath, '')
  const [umapPalette, setUmapPalette] = useState('default')
  const [activeTab, setActiveTab] = useState(() => {
    try { const s = sessionStorage.getItem('gensci_active_tab'); return s ? parseInt(s, 10) : 0 } catch { return 0 }
  })

  useEffect(() => { try { sessionStorage.setItem('gensci_active_tab', String(activeTab)) } catch { /* ignore */ } }, [activeTab])

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

  // 摘要分两段取：/api/analysis-info 只带服务端**已经缓存**的那份，冷缓存时
  // 它给的是 abstract_ready=false + abstract=null，这里再补一次。
  //
  // 为什么必须拆开（BUG_LOG B35）：摘要要经公司代理发外部 HTTP，实测 4s~125s，
  // 而 stats 是本地缓存、毫秒级。两者同在一个响应里时，摘要会把整页拖过
  // apiFetch 的 60s 超时，用户看到 "Failed to load info" —— 连本来已经拿到的
  // stats 都一起丢了。
  //
  // 失败**只降级到摘要那一块**：stats 那时已经渲染在屏幕上，不能因为摘要取不到
  // 就把整页切成错误屏。摘要有 20s 的服务端总时限兜底，所以这里也不会久等。
  //
  // 失败必须「说得出失败」并且**能重试**。以前这里是个空 .catch：取不到就
  // 等同「Abstract not available」，而且 needsAbstract 的依赖没变化、effect
  // 不会重跑，用户只能刷新整页 —— 而服务端本来就是按「下次请求重试」设计的
  // （pubmed.py 失败不写缓存）。前端把这个重试机会整个丢掉了。
  const needsAbstract = info != null && info.abstract_ready !== true
  useEffect(() => {
    if (!realPath || !pmid || !needsAbstract) return
    let cancelled = false
    setAbstractError(false)
    fetchAbstract(pmid)
      .then((res) => {
        if (cancelled) return
        setInfo((prev) => (prev ? { ...prev, abstract: res.abstract, abstract_ready: res.abstract_ready } : prev))
        // abstract_ready=false 表示服务端还没拿到「最终答案」（它不缓存残缺记录），
        // 不等于「这篇没有摘要」，所以按可重试处理。
        setAbstractError(res.abstract_ready !== true)
      })
      .catch(() => {
        if (!cancelled) setAbstractError(true)
      })
    return () => { cancelled = true }
  }, [realPath, pmid, needsAbstract, abstractNonce])

  const fetchUmap = useCallback(() => {
    if (!realPath) return
    setUmapLoading(true)
    fetchUmapData(realPath, colorBy, 50000, colorBy === 'Gene' ? geneName : undefined, umapPalette, colorBy === 'Gene' ? geneName2 : undefined)
      .then((d) => setUmapData(d as UmapData)).catch(() => setUmapData(null)).finally(() => setUmapLoading(false))
  }, [realPath, colorBy, geneName, geneName2, umapPalette])

  useEffect(() => {
    if (!realPath || activeTab !== 1) return
    // No cleanup: there used to be a `cancelled` flag here, but nothing ever
    // read it — the fetch sets state through fetchUmap regardless, so it
    // promised a cancellation guard that did not exist. realPath is listed
    // because the guard above reads it; fetchUmap already closes over it, so
    // they change together and this cannot cause a second fetch.
    fetchUmap()
  }, [fetchUmap, activeTab, realPath])

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
            <div className="flex-1 min-h-0">
              <InfoPanel
                info={info}
                loading={infoLoading}
                abstractError={abstractError}
                onRetryAbstract={retryAbstract}
                isBulk={isTabular}
              />
            </div>
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
