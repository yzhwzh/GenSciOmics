import { useCallback, useEffect, useState } from 'react'

/**
 * The gene box remembers what was last selected, so switching to Free Analysis
 * and back does not reset it (AnalysisPage mounts only the active tab).
 *
 * The stored gene used to be a single unscoped key, which meant it belonged to
 * no dataset in particular. Two ways that produced a wrong plot:
 *
 *  - A name saved under an older build — before B28 guarded the commit path —
 *    is read back verbatim and sent to the backend, which resolves unknown
 *    tokens by substring (server/analysis/utils.py:124). "CD3" (not in the
 *    dataset) drew ABCD3, with nothing on screen saying so. See BUG_LOG B28/B34.
 *  - Even a *valid* gene carried across datasets is wrong: pick FAP on dataset
 *    A, open dataset B, and B restores FAP and plots it without the user ever
 *    having asked for it here.
 *
 * So the key is scoped to the dataset. The legacy unscoped keys are simply
 * never read again — old values go stale rather than being migrated, which is
 * the point: they were never known to be valid for any particular dataset.
 *
 * Kept out of the containers (and out of geneInput.ts, which is pure logic) so
 * the read/write pair — and the ordering rule below — lives in one place.
 */

export const BOXPLOT_GENE_KEY = 'gensci_boxplot_gene'
export const AGG_GENE_KEY = 'gensci_agg_gene'
export const UMAP_GENE_KEY = 'gensci_gene_name'
export const UMAP_GENE2_KEY = 'gensci_gene_name2'
export const BULK_GENE_KEY = 'gensci_bulk_gene'

/** Storage key for one gene box on one dataset. */
export function storedGeneKey(baseKey: string, realPath: string): string {
  return `${baseKey}::${realPath}`
}

/** The stored gene for this dataset, or `fallback` when there is nothing to read. */
export function readStoredGene(baseKey: string, realPath: string, fallback: string): string {
  // An empty path means the dataset has not loaded yet, so there is nothing to
  // scope to. Without this, the empty key would be read and written as if it
  // were a dataset of its own.
  if (!realPath) return fallback
  try {
    return sessionStorage.getItem(storedGeneKey(baseKey, realPath)) ?? fallback
  } catch {
    // sessionStorage throws in private mode / when disabled.
    return fallback
  }
}

/**
 * `[gene, setGene]`, persisted per dataset.
 *
 * The write effect refuses to run until the slot in state has been adopted, and
 * that gate is not cosmetic. AnalysisPage swaps `realPath` in an effect
 * (AnalysisPage.tsx:77-103) without remounting its children, so for one render a
 * container holds dataset A's gene next to dataset B's path. Writing in that
 * render would file A's gene under B's key — the very leak this exists to
 * prevent. Reached by back/forward between two analysis URLs; the usual route in
 * goes through TissuePage, which unmounts this page and resets the pair.
 *
 * The same gate covers AnalysisPage's own case, where the gene is initialised
 * before `realPath` has arrived: writing then would blank the stored value with
 * ''.
 */
export function useStoredGene(
  baseKey: string,
  realPath: string,
  fallback: string,
): readonly [string, (gene: string) => void] {
  const [gene, setGene] = useState(() => readStoredGene(baseKey, realPath, fallback))
  // The exact slot the state above belongs to — box and dataset both. Seeded from
  // the first render so a container mounting with a known path can write at once.
  // It is the scoped key rather than `realPath` because a box changing while the
  // dataset stays put must re-read too; gating on the path alone would leave the
  // old box's gene in state and then write it into the new box's slot.
  const slot = realPath ? storedGeneKey(baseKey, realPath) : ''
  const [adopted, setAdopted] = useState(slot)

  useEffect(() => {
    if (!slot || adopted === slot) return
    setAdopted(slot)
    setGene(readStoredGene(baseKey, realPath, fallback))
  }, [slot, baseKey, realPath, fallback, adopted])

  useEffect(() => {
    if (!slot || adopted !== slot) return
    try {
      sessionStorage.setItem(slot, gene)
    } catch {
      // Ignore: persistence is a convenience, never a correctness requirement.
    }
  }, [slot, adopted, gene])

  const select = useCallback((next: string) => { setGene(next) }, [])
  return [gene, select] as const
}
