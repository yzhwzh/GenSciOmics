/**
 * Guard for the three free-text gene boxes (Tab 2 Gene, Tab 3 Gene, Tab 3
 * GENE2 in single mode).
 *
 * Those inputs render a suggestion dropdown that is a *hint*, not a
 * constraint: Enter commits whatever is in the box, and `onBlur` commits it
 * too — so clicking anywhere else is enough, no keystroke required. The typed
 * text was never compared against the listed genes.
 *
 * The backend then resolved the token by substring (`server/analysis/utils.py:124`,
 * `partial = [n for n in var_names if g.lower() in n.lower()]`) and reported
 * the result as resolved. Measured against the live Lung IPF dataset (33,694
 * genes): "CD3" -> "ABCD3", "COL1" -> "COL16A1", "A1" -> "VWA1". The plot, the
 * table header and the numbers all look entirely plausible, so nothing
 * downstream can catch it. The check has to happen here.
 *
 * See BUG_LOG B28.
 */

/**
 * What a rejected gene box tells the reader.
 *
 * Exported so the components and their tests read from one source. A hand-copied
 * string in the test drifts the moment the wording changes, and the assertion
 * silently stops testing anything.
 */
export function unknownGeneMessage(typed: string): string {
  return `No gene named “${typed}” in this dataset`
}

/**
 * What a box says when the backend plotted a different gene than the one asked
 * for — or '' when it used the gene as given.
 *
 * The guard above only covers a gene the user *types*. A gene restored from
 * storage, or typed into a box that has no guard (UMAP's), reaches the backend
 * unchecked, where the same substring fallback resolves it to something else
 * and returns an ordinary-looking plot. This line is the only place that tells
 * the reader which gene they are actually looking at.
 *
 * `resolved` is `undefined` for responses cached before the backend reported
 * the field, which is "the backend did not say", not "the backend substituted".
 * A pure case difference ("egfr" -> "EGFR") is the box working correctly, and
 * warning about it would teach the reader to skip the line that matters.
 */
export function resolvedGeneMessage(typed: string, resolved?: string): string {
  if (!resolved) return ''
  if (typed.trim().toLowerCase() === resolved.toLowerCase()) return ''
  return `“${typed}” matched nothing here — showing “${resolved}” instead`
}

/** What the caller should do with what the user typed. */
export type GeneChoice =
  | { kind: 'commit'; gene: string }
  | { kind: 'reject'; typed: string; suggestions: string[] }
  | { kind: 'ignore' }

/**
 * The canonical gene name for `typed`, or null when this dataset has no gene
 * spelled exactly that way.
 *
 * Returns the *candidate's* spelling rather than the typed one, so typing
 * "egfr" stores "EGFR" and the rest of the app sees one consistent name.
 */
export function exactGeneMatch(typed: string, candidates: readonly string[]): string | null {
  const lowered = typed.trim().toLowerCase()
  if (!lowered) return null
  return candidates.find((c) => c.toLowerCase() === lowered) ?? null
}

/**
 * Decide what a submitted gene box means.
 *
 * `listed` is what the dropdown is currently showing, which lags by the 200ms
 * search debounce — a gene typed in one go is usually not in it yet. Refusing
 * on that basis would reject real genes, so a miss falls through to asking the
 * server for this exact text before giving up.
 *
 * A failed lookup rejects rather than committing the raw text: falling back to
 * "use it anyway" is precisely the bug this exists to prevent.
 */
export async function resolveGeneChoice(
  typed: string,
  listed: readonly string[],
  search: (query: string) => Promise<string[]>,
): Promise<GeneChoice> {
  const text = typed.trim()
  if (!text) return { kind: 'ignore' }

  const listedHit = exactGeneMatch(text, listed)
  if (listedHit) return { kind: 'commit', gene: listedHit }

  let fresh: string[] = []
  try {
    fresh = await search(text)
  } catch {
    // A failed lookup is not a licence to commit: `fresh` stays empty and the
    // exact-match check below rejects, rather than falling through to a guess.
  }

  const hit = exactGeneMatch(text, fresh)
  return hit ? { kind: 'commit', gene: hit } : { kind: 'reject', typed: text, suggestions: fresh }
}
