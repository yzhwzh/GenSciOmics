import { AlertTriangle } from 'lucide-react'
import { resolvedGeneMessage } from './geneInput'

/**
 * Says which gene the backend actually plotted, when that is not the one asked
 * for. See geneInput.ts / BUG_LOG B34.
 *
 * Sits under the Gene box rather than over the chart: a substituted gene
 * produces a completely ordinary-looking plot, so there is nothing to see on
 * the chart itself — the reader's eye is on the box they just used.
 *
 * `resolution` is paired with the gene it belongs to because the two arrive at
 * different times. `asked` is what the box says now; `resolution.asked` is what
 * the plot on screen was made from. They disagree for the render between
 * choosing a gene and the new plot arriving, and rendering the old gene's
 * substitution against the new name would caption a correct plot with a wrong
 * warning — the same class of mistake this whole change is about.
 *
 * Returns null when nothing was substituted, so callers render unconditionally.
 */
interface ResolvedGeneNoticeProps {
  asked: string
  resolution: { asked: string; resolved: string } | null
}

export default function ResolvedGeneNotice({ asked, resolution }: ResolvedGeneNoticeProps) {
  if (!resolution || resolution.asked !== asked) return null
  const text = resolvedGeneMessage(resolution.asked, resolution.resolved)
  if (!text) return null
  return (
    <div
      role="status"
      className="flex items-start gap-1 text-[10px] leading-snug text-amber-700 mt-1"
    >
      <AlertTriangle className="w-3 h-3 shrink-0 mt-px" />
      <span>{text}</span>
    </div>
  )
}
