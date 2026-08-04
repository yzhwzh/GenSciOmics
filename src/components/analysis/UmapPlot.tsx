import { useEffect, useRef, useState, useCallback } from 'react'
import { Loader2 } from 'lucide-react'
import * as echarts from 'echarts'
import { formatNumber } from '../../api/client'
import DualGeneColorMap from './DualGeneColorMap'
import type { UmapData } from '../../api/types'

export default function UmapPlot({
  data, loading, colorBy, onColorByChange, geneName, onGeneNameChange, geneName2, onGeneName2Change,
}: {
  data: UmapData | null; loading: boolean
  colorBy: string; onColorByChange: (v: string) => void
  geneName: string; onGeneNameChange: (v: string) => void
  geneName2: string; onGeneName2Change: (v: string) => void
}) {
  const chartRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)
  const isDualGene = data?.color_type === 'dual_gene'
  const isContinuous = data?.color_type === 'continuous'

  // Draggable legend position
  const [legendOff, setLegendOff] = useState({ x: 0, y: 0 })
  const dragRef = useRef<{ active: boolean; startX: number; startY: number; offX: number; offY: number }>({
    active: false, startX: 0, startY: 0, offX: 0, offY: 0,
  })

  const legendRef = useRef<HTMLDivElement>(null)

  const onDragStart = useCallback((clientX: number, clientY: number) => {
    const d = dragRef.current
    d.active = true
    d.startX = clientX
    d.startY = clientY
    d.offX = legendOff.x
    d.offY = legendOff.y
  }, [legendOff])

  const onDragMove = useCallback((clientX: number, clientY: number) => {
    const d = dragRef.current
    if (!d.active) return
    setLegendOff({ x: d.offX + clientX - d.startX, y: d.offY + clientY - d.startY })
  }, [])

  const onDragEnd = useCallback(() => {
    dragRef.current.active = false
  }, [])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => onDragMove(e.clientX, e.clientY)
    const onMouseUp = () => onDragEnd()
    const onTouchMove = (e: TouchEvent) => { if (e.touches[0]) onDragMove(e.touches[0].clientX, e.touches[0].clientY) }
    const onTouchEnd = () => onDragEnd()
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    window.addEventListener('touchmove', onTouchMove, { passive: true })
    window.addEventListener('touchend', onTouchEnd)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('touchend', onTouchEnd)
    }
  }, [onDragMove, onDragEnd])

  useEffect(() => {
    if (!chartRef.current) return
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current, null, { renderer: 'canvas' })
    }
    return () => { instanceRef.current?.dispose(); instanceRef.current = null }
  }, [])

  useEffect(() => {
    const chart = instanceRef.current
    if (!chart || !data || loading) return

    const isContinuous = data.color_type === 'continuous'
    const pointCount = data.points.length

    let scatterData: unknown
    let encodeOpt: Record<string, string> | undefined = undefined

    if (isDualGene) {
      // Dual-gene: per-point RGB colors, preserve 4 values for tooltip
      scatterData = data.points.map((p, i) => ({
        value: p, // [x, y, expr1, expr2]
        itemStyle: data.colors[i] ? { color: data.colors[i] } : undefined,
      }))
    } else if (isContinuous) {
      scatterData = data.points.map((p, i) => ({
        value: p,
        itemStyle: data.colors[i] ? { color: data.colors[i] } : undefined,
      }))
    } else {
      // Categorical: per-point colors from backend
      scatterData = data.points.map((p, i) => ({
        value: p,
        itemStyle: data.colors[i] ? { color: data.colors[i] } : undefined,
      }))
    }

    const opt: echarts.EChartsOption = {
      visualMap: { show: false } as any,
      backgroundColor: 'transparent',
      grid: { left: 35, right: 10, top: 10, bottom: 25 },
      xAxis: {
        type: 'value', splitLine: { show: false },
        axisLabel: { show: false }, axisTick: { show: false },
        name: 'UMAP1', nameLocation: 'center', nameGap: 18,
        nameTextStyle: { fontSize: 10, color: '#999' },
      },
      yAxis: {
        type: 'value', splitLine: { show: false },
        axisLabel: { show: false }, axisTick: { show: false },
        name: 'UMAP2', nameLocation: 'center', nameGap: 22,
        nameTextStyle: { fontSize: 10, color: '#999' },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, yAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseWheel: true },
        { type: 'slider', xAxisIndex: 0, height: 8, bottom: 0, borderColor: '#ddd', fillerColor: 'rgba(59,130,246,0.1)', handleStyle: { color: '#3b82f6' } },
      ],
      toolbox: {
        feature: {
          dataZoom: { yAxisIndex: 'none', title: { zoom: 'Zoom', back: 'Reset' } },
          restore: { title: 'Reset' },
        },
        right: 30,
        top: 0,
        iconStyle: { borderColor: '#999', borderWidth: 1 },
      },
      series: [{
        type: 'scatter',
        data: scatterData as any,
        encode: encodeOpt,
        symbolSize: pointCount > 50000 ? 1.5 : pointCount > 20000 ? 2 : pointCount > 5000 ? 2.5 : 3,
        animation: false,
      }],
      tooltip: {
        trigger: 'item',
        formatter: (params: unknown) => {
          const p = params as { data: { value: number[] }, dataIndex: number }
          if (!p?.data?.value) return ''
          const vals = p.data.value
          if (isDualGene && vals.length >= 4 && data.legend.length >= 2) {
            return `UMAP1: ${vals[0]?.toFixed(2) ?? ''}<br/>UMAP2: ${vals[1]?.toFixed(2) ?? ''}<br/>
              <span style="color:#ff0000">●</span> ${data.legend[0]?.name ?? 'Gene1'}: <strong>${vals[2]?.toFixed(4) ?? ''}</strong><br/>
              <span style="color:#00ff00">●</span> ${data.legend[1]?.name ?? 'Gene2'}: <strong>${vals[3]?.toFixed(4) ?? ''}</strong>`
          }
          if (isContinuous && vals.length >= 3) {
            return `UMAP1: ${vals[0]?.toFixed(2) ?? ''}<br/>UMAP2: ${vals[1]?.toFixed(2) ?? ''}<br/><strong>${data.legend[0]?.name ?? 'Expression'}: ${vals[2]?.toFixed(4) ?? ''}</strong>`
          }
          return `UMAP1: ${vals[0]?.toFixed(2) ?? ''}<br/>UMAP2: ${vals[1]?.toFixed(2) ?? ''}`
        },
      },
    }
    chart.setOption(opt, true)
  }, [data, loading, isDualGene])

  useEffect(() => {
    const chart = instanceRef.current
    if (!chart || !chartRef.current) return
    let rafId: number
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafId)
      rafId = requestAnimationFrame(() => chart.resize())
    })
    ro.observe(chartRef.current)
    return () => { ro.disconnect(); cancelAnimationFrame(rafId) }
  }, [])

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-3 py-1 border-b border-border-light shrink-0">
        <span className="text-[11px] font-medium text-text-muted">Color by</span>
        <select value={colorBy} onChange={(e) => onColorByChange(e.target.value)}
          className="text-xs border border-border-light rounded px-2 py-0.5 bg-surface text-text-secondary outline-none focus:border-blue-400">
          <option value="CellType">CellType</option>
          <option value="Patient">Patient</option>
          <option value="Sample">Sample</option>
          <option value="Gene">Gene expression</option>
        </select>
        {colorBy === 'Gene' && (
          <div className="flex items-center gap-1">
            <input type="text" value={geneName} onChange={(e) => onGeneNameChange(e.target.value)}
              placeholder="Gene1" className="text-xs border border-border-light rounded px-2 py-0.5 bg-surface text-text-secondary outline-none focus:border-blue-400 w-[72px]" />
            <input type="text" value={geneName2} onChange={(e) => onGeneName2Change(e.target.value)}
              placeholder="Gene2" className="text-xs border border-border-light rounded px-2 py-0.5 bg-surface text-text-secondary outline-none focus:border-blue-400 w-[72px]" />
          </div>
        )}
        {data?.sampled && data.n_cells > 0 && (
          <span className="text-[10px] text-text-muted ml-auto" title={`Dataset has ${data.n_cells.toLocaleString()} cells — showing 1 out of every ${data.sample_step} points for performance`}>
            {data.n_cells.toLocaleString()} cells · shown 1/{data.sample_step}
          </span>
        )}
      </div>
      <div className="flex-1 relative">
        {(loading || !data) && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface/60 z-10">
            <Loader2 className="w-5 h-5 text-brand animate-spin" />
          </div>
        )}
        <div ref={chartRef} className="w-full h-full" />

        {/* Dual-gene 2D Color Threshold map (draggable) */}
        {isDualGene && data.legend.length >= 2 && (
          <div
            ref={legendRef}
            onMouseDown={(e) => onDragStart(e.clientX, e.clientY)}
            onTouchStart={(e) => { if (e.touches[0]) onDragStart(e.touches[0].clientX, e.touches[0].clientY) }}
            className="absolute cursor-grab active:cursor-grabbing"
            style={{ top: 1 + legendOff.y, right: 1 - legendOff.x }}
          >
            <DualGeneColorMap
              gene1Name={data.legend[0].name}
              gene2Name={data.legend[1].name}
              gene1Max={data.legend[0].max ?? 0}
              gene2Max={data.legend[1].max ?? 0}
            />
          </div>
        )}

        {/* Standard categorical legend (CellType, Patient, Sample) — draggable */}
        {data?.color_type === 'categorical' && data.legend.length > 0 && data.legend.length <= 100 && (
          <div
            ref={legendRef}
            onMouseDown={(e) => onDragStart(e.clientX, e.clientY)}
            onTouchStart={(e) => { if (e.touches[0]) onDragStart(e.touches[0].clientX, e.touches[0].clientY) }}
            className="absolute cursor-grab active:cursor-grabbing bg-surface/90 rounded-lg border border-border-light p-2 text-[11px] max-h-[85%] overflow-y-auto max-w-[200px] shadow-md backdrop-blur-sm"
            style={{ top: 1 + legendOff.y, right: 1 - legendOff.x }}
          >
            {data.legend.map((item) => (
              <div key={item.name} className="flex items-center gap-2 py-[2px] hover:bg-surface-raised rounded px-1 -mx-1">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
                <span className="text-text-secondary truncate">{item.name}</span>
                {item.count != null && <span className="text-text-muted ml-auto tabular-nums">{formatNumber(item.count)}</span>}
              </div>
            ))}
          </div>
        )}

        {/* Single-gene expression legend (draggable gradient bar) */}
        {isContinuous && data.legend[0] && (
          <div
            ref={legendRef}
            onMouseDown={(e) => onDragStart(e.clientX, e.clientY)}
            onTouchStart={(e) => { if (e.touches[0]) onDragStart(e.touches[0].clientX, e.touches[0].clientY) }}
            className="absolute cursor-grab active:cursor-grabbing bg-surface/90 rounded-lg border border-border-light p-2 shadow-md backdrop-blur-sm select-none"
            style={{ top: 1 + legendOff.y, right: 1 - legendOff.x }}
          >
            <div className="flex items-stretch gap-2">
              {/* Gradient bar */}
              <div
                className="w-3 rounded-sm shrink-0"
                style={{
                  height: 80,
                  background: 'linear-gradient(to top, #fff5f0, #fee0d2, #fc9272, #de2d26, #a50f15)',
                }}
              />
              {/* Labels */}
              <div className="flex flex-col justify-between text-[10px] text-text-muted leading-none py-0.5">
                <span>{data.legend[0].max != null ? data.legend[0].max.toFixed(2) : ''}</span>
                <span>{data.legend[0].min != null ? data.legend[0].min.toFixed(2) : ''}</span>
              </div>
            </div>
            <div className="text-[10px] text-text-muted font-medium text-center mt-1 pt-1 border-t border-border-light">
              {data.legend[0].name}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
