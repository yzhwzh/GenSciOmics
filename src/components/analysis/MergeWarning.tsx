import { AlertTriangle } from 'lucide-react'
import type { MergeOp } from '../../api/types'
import { mergeWarningText } from './mergeOp'

/**
 * Warning for Merge-gene specs whose members did not all resolve.
 *
 * The backend reports which names matched (`gene2_resolved`) and which did not
 * (`gene2_unresolved`). We render the notice next to each consumer rather than
 * once in the container: the 共表达 panel is hidden in Mean mode while the tables
 * are not, so a notice living only in the panel would silently disappear exactly
 * when the user is reading AND-aggregated numbers.
 *
 * Returns null when nothing was missing, so callers can render unconditionally.
 */
interface MergeWarningProps {
  unresolved?: string[]
  resolved?: string[]
  op?: MergeOp
}

export default function MergeWarning({ unresolved = [], resolved = [], op = 'or' }: MergeWarningProps) {
  const text = mergeWarningText({ unresolved, resolved, op })
  if (!text) return null
  return (
    <div
      role="status"
      className="flex items-start gap-1 px-2 py-1 text-[10px] leading-snug text-amber-700 bg-amber-50 border-b border-amber-200"
    >
      <AlertTriangle className="w-3 h-3 shrink-0 mt-px" />
      <span>{text}</span>
    </div>
  )
}
