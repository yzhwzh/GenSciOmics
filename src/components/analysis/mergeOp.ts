/**
 * Pure helpers for the Merge-gene 或/且 operator.
 *
 * Kept out of ExpressionChartContainer.tsx so that module exports only its
 * component (react-refresh does a full reload when a .tsx module exports
 * non-components), and so tests can reach these without pulling in react-select.
 */
import type { MergeOp } from '../../api/types'

export const MERGE_OP_KEY = 'gensci_agg_merge_op'

/** Applied 或/且 choice, restored per browser session. Anything but 'and' means 'or'. */
export function readStoredOp(): MergeOp {
  try { return sessionStorage.getItem(MERGE_OP_KEY) === 'and' ? 'and' : 'or' } catch { return 'or' }
}

/**
 * Which operator actually reaches the backend for the current Merge state.
 *
 * Single-gene mode never merges, and a degenerate 0/1-member set either sends no
 * gene2 at all or falls back to a real per-gene row where the operator cannot
 * change the result. Forcing 'or' there keeps those URLs byte-identical to before
 * this feature existed.
 */
export function deriveG2Op(mode: 'single' | 'merge', runLen: number, runOp: MergeOp): MergeOp {
  return mode === 'merge' && runLen >= 2 ? runOp : 'or'
}

/** Cap on member names spelled out in one warning, so a pasted list can't overflow the panel. */
const MAX_NAMED_MISSING = 3

function nameMissing(unresolved: string[]): string {
  if (unresolved.length <= MAX_NAMED_MISSING) return unresolved.join('、')
  const shown = unresolved.slice(0, MAX_NAMED_MISSING).join('、')
  return `${shown} 等 ${unresolved.length} 个`
}

export interface MergeWarningInput {
  unresolved: string[]
  resolved: string[]
  op: MergeOp
}

/**
 * Warning text for a Merge spec whose members did not all resolve, or null when
 * nothing was missing.
 *
 * `resolved` must come from the backend rather than the frontend chip count: the
 * backend de-duplicates case-insensitively and has a partial-match fallback, so
 * both the names and the count can differ from what the user typed.
 */
export function mergeWarningText({ unresolved, resolved, op }: MergeWarningInput): string | null {
  if (!unresolved.length) return null
  const missing = nameMissing(unresolved)
  if (resolved.length >= 2) {
    return `未找到 ${missing}；已按 ${resolved.length} 个基因${op === 'and' ? '取交集' : '取并集'}`
  }
  if (resolved.length === 1) {
    // is_merge is false with a single member, so the backend falls back to the real
    // gene: GeneMeanExpression becomes a continuous value, not the 0/1 the user expected.
    return `未找到 ${missing}；已退化为单基因 ${resolved[0]}（不再合并）`
  }
  return `未找到 ${missing}；未合并出合成基因，表中只有主基因`
}
