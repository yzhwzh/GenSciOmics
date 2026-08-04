import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { fetchPlot } from '../../api/analysis'
import ZoomableImage from './ZoomableImage'

export default function PlotImage({
  realPath, gene, conditionCol, metric, plotType, minCells, palette = 'default',
}: {
  realPath: string; gene: string
  conditionCol: string; metric: string; plotType: 'boxplot' | 'barplot'
  minCells?: number; palette?: string
}) {
  const [src, setSrc] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!realPath || !gene) return
    setLoading(true); setErr(null); setSrc(null)
    fetchPlot(realPath, gene, conditionCol, metric, plotType, minCells, palette)
      .then(d => {
        if (d.error) { setErr(d.error); console.error('Plot API error:', d.error) }
        else if (d.image) { setSrc(`data:image/png;base64,${d.image}`) }
      }).catch(e => { setErr(e.message); console.error('Plot fetch error:', e) })
      .finally(() => setLoading(false))
  }, [realPath, gene, conditionCol, metric, plotType, minCells, palette])

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
