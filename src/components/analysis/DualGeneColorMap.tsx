import { useRef, useEffect } from 'react'

interface Props {
  gene1Name: string
  gene2Name: string
  gene1Max: number
  gene2Max: number
  /** Grid size in logical pixels; overall canvas scales proportionally (default 130) */
  gridSize?: number
}

const _GS = 10 // Seurat 10×10 grid

function _blendColor(colIdx: number, rowIdx: number): string {
  // Seurat BlendMatrix: lightgrey → pure red/green/yellow via 10×10 grid
  const NEG = [211, 211, 211]
  const G1 = [255, 0, 0]
  const G2 = [0, 255, 0]
  const t1 = colIdx / (_GS - 1)
  const t2 = rowIdx / (_GS - 1)
  const mx = Math.max(t1, t2)
  let r: number, g: number, b: number
  if (mx < 1e-6) {
    ;[r, g, b] = NEG
  } else {
    const w1 = t1 / mx
    const w2 = t2 / mx
    r = Math.min(255, Math.round(NEG[0] + (G1[0] * w1 + G2[0] * w2 - NEG[0]) * mx))
    g = Math.min(255, Math.round(NEG[1] + (G1[1] * w1 + G2[1] * w2 - NEG[1]) * mx))
    b = Math.min(255, Math.round(NEG[2] + (G1[2] * w1 + G2[2] * w2 - NEG[2]) * mx))
  }
  return `rgb(${r},${g},${b})`
}

export default function DualGeneColorMap({ gene1Name, gene2Name, gene1Max, gene2Max, gridSize = 130 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const s = gridSize / 130 // scale factor relative to base size

  const GRID = Math.max(60, gridSize)
  const ML = Math.round(38 * s)
  const MB = Math.round(34 * s)
  const MT = Math.round(16 * s)
  const MR = Math.round(18 * s)
  const CW = ML + GRID + MR
  const CH = MT + GRID + MB
  const FONT_SIZE = Math.max(8, Math.round(10 * s))
  const TICK_LEN = Math.max(3, Math.round(5 * s))

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = CW * dpr
    canvas.height = CH * dpr
    ctx.scale(dpr, dpr)

    // ── Background ──
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, CW, CH)

    // ── Color grid: _GS × _GS solid squares (Seurat BlendMap style) ──
    const gx0 = ML, gy0 = MT
    const cellSize = GRID / _GS
    for (let col = 0; col < _GS; col++) {
      for (let row = 0; row < _GS; row++) {
        // row=0(top) → Gene2 high, row=_GS-1(bottom) → Gene2 low
        ctx.fillStyle = _blendColor(col, _GS - 1 - row)
        ctx.fillRect(gx0 + col * cellSize, gy0 + row * cellSize, cellSize, cellSize)
      }
    }

    // ── Grid lines between cells (separable squares) ──
    ctx.strokeStyle = '#ccc'
    ctx.lineWidth = 0.5
    for (let i = 0; i <= _GS; i++) {
      const x = gx0 + i * cellSize
      ctx.beginPath(); ctx.moveTo(x, gy0); ctx.lineTo(x, gy0 + GRID); ctx.stroke()
      const y = gy0 + i * cellSize
      ctx.beginPath(); ctx.moveTo(gx0, y); ctx.lineTo(gx0 + GRID, y); ctx.stroke()
    }

    // ── Tick marks & labels ──
    ctx.fillStyle = '#666'
    ctx.font = `${FONT_SIZE}px sans-serif`
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'

    // Gene2 ticks (left side, 5 ticks)
    const g2Ticks = [0, 0.25, 0.5, 0.75, 1].map(f => ({
      val: gene2Max * f,
      label: gene2Max > 0 ? (gene2Max * f).toFixed(1) : '0',
      y: gy0 + (1 - f) * GRID,
    }))
    for (const t of g2Ticks) {
      ctx.fillText(t.label, gx0 - 6, t.y)
      ctx.strokeStyle = '#bbb'
      ctx.lineWidth = 0.5
      ctx.beginPath(); ctx.moveTo(gx0 - TICK_LEN, t.y); ctx.lineTo(gx0, t.y); ctx.stroke()
    }

    // Gene1 ticks (bottom, 5 ticks)
    const g1Ticks = [0, 0.25, 0.5, 0.75, 1].map(f => ({
      val: gene1Max * f,
      label: gene1Max > 0 ? (gene1Max * f).toFixed(1) : '0',
      x: gx0 + f * GRID,
    }))
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    for (const t of g1Ticks) {
      ctx.fillText(t.label, t.x, gy0 + GRID + 4)
      ctx.strokeStyle = '#bbb'
      ctx.lineWidth = 0.5
      ctx.beginPath(); ctx.moveTo(t.x, gy0 + GRID); ctx.lineTo(t.x, gy0 + GRID + TICK_LEN); ctx.stroke()
    }

    // ── Axis labels ──
    ctx.fillStyle = '#888'
    ctx.font = `bold ${FONT_SIZE}px sans-serif`

    // Gene2 (left, rotated)
    ctx.save()
    ctx.translate(Math.round(11 * s), gy0 + GRID / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    const maxNameLen = Math.round(16 * s)
    ctx.fillText(gene2Name.length > maxNameLen ? gene2Name.slice(0, maxNameLen - 2) + '…' : gene2Name, 0, 0)
    ctx.restore()

    // Gene1 (bottom center, below tick labels)
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    const g1Label = gene1Name.length > maxNameLen ? gene1Name.slice(0, maxNameLen - 2) + '…' : gene1Name
    ctx.fillText(g1Label, gx0 + GRID / 2, gy0 + GRID + 4 + FONT_SIZE + 2)
  }, [gene1Name, gene2Name, gene1Max, gene2Max, GRID, ML, MB, MT, CW, CH, FONT_SIZE, TICK_LEN, s])

  return (
    <div className="bg-surface/95 rounded-lg border border-border-light shadow-md backdrop-blur-sm select-none inline-block leading-none">
      <canvas
        ref={canvasRef}
        style={{ width: CW, height: CH, display: 'block' }}
      />
    </div>
  )
}
