import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { fetchPlot } from '../../api/analysis'
import ZoomableImage from './ZoomableImage'

/**
 * `onResolvedGene` reports the var name the backend actually plotted, and '' for
 * every state where there is nothing to report (no request yet, in flight, or
 * failed). It exists because the backend resolves an unknown token by substring
 * — "CD3" plots "ABCD3" and returns an ordinary-looking image — so the only way
 * the caller can say which gene is on screen is for this component to hand it
 * back. Must be a stable reference (a `useState` setter qualifies): it is an
 * effect dependency, so a fresh closure per render would refetch on every render.
 */
export default function PlotImage({
  realPath, gene, conditionCol, metric, plotType, minCells, palette = 'default', onResolvedGene,
}: {
  realPath: string; gene: string
  conditionCol: string; metric: string; plotType: 'boxplot' | 'barplot'
  minCells?: number; palette?: string
  onResolvedGene?: (gene: string) => void
}) {
  const [src, setSrc] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!realPath || !gene) return
    // Each /api/plot is a real matplotlib render (seconds on a cold cache), and a
    // new one can start while the previous is still in flight — pick two genes in
    // quick succession and the slower, older request lands last. Dropping stale
    // answers is what keeps the image and its report in step: the report is
    // ignored when its `asked` no longer matches the box, so a stale pair would
    // leave the previous gene's plot on screen under the new gene's name with
    // the very notice that says so suppressed.
    let stale = false
    setLoading(true); setErr(null); setSrc(null)
    // Clear the previous gene's report first: until this request answers, nothing
    // on screen corresponds to a resolved name, and reporting the old one would
    // caption the new plot with the old gene.
    onResolvedGene?.('')
    fetchPlot(realPath, gene, conditionCol, metric, plotType, minCells, palette)
      .then(d => {
        if (stale) return
        if (d.error) { setErr(d.error); console.error('Plot API error:', d.error) }
        else if (d.image) {
          setSrc(`data:image/png;base64,${d.image}`)
          onResolvedGene?.(d.gene_resolved ?? '')
        }
      }).catch(e => {
        if (stale) return
        setErr(e instanceof Error ? e.message : String(e))
        console.error('Plot fetch error:', e)
      })
      .finally(() => { if (!stale) setLoading(false) })
    return () => { stale = true }
  }, [realPath, gene, conditionCol, metric, plotType, minCells, palette, onResolvedGene])

  return (
    <div className="relative flex items-center justify-center w-full h-full">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface/60 z-10">
          <Loader2 className="w-5 h-5 text-brand animate-spin" />
        </div>
      )}
      {err && (
        <div className="text-sm text-text-muted p-4 text-center">{err}</div>
      )}
      {src && (
        <ZoomableImage src={src} alt={`${plotType} plot`} className="max-w-full max-h-full object-contain" />
      )}
    </div>
  )
}
