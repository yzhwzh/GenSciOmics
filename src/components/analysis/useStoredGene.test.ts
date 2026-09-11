import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useStoredGene, readStoredGene, storedGeneKey, AGG_GENE_KEY } from './useStoredGene'

/**
 * The gene boxes remember their selection so that switching to Free Analysis and
 * back does not reset it (AnalysisPage keeps only the active tab mounted).
 *
 * That memory must never outlive the dataset it belongs to. The backend resolves
 * an unknown name by substring (server/analysis/utils.py:124), so a name carried
 * over from another dataset comes back as a perfectly plausible plot of a
 * *different* gene — which is exactly how "CD3" (not in the dataset) ended up
 * drawing ABCD3 after it was restored from an older build's stored value.
 */
const PATH_A = '/data/Human/Lung/IPF/scRNA/a.h5ad'
const PATH_B = '/data/Human/Lung/COPD/scRNA/b.h5ad'

const stored = (key: string): string | null => {
  try { return sessionStorage.getItem(key) } catch { return null }
}

describe('useStoredGene — the stored gene is scoped to one dataset', () => {
  beforeEach(() => { try { sessionStorage.clear() } catch { /* ignore */ } })
  afterEach(() => { try { sessionStorage.clear() } catch { /* ignore */ } })

  it('ignores a legacy unscoped value and falls back to the default', () => {
    // The reported state: an older build committed the raw text under the old,
    // unscoped key. It must not be adopted, or it drives a fetch on mount.
    sessionStorage.setItem(AGG_GENE_KEY, 'CD3')
    const { result } = renderHook(() => useStoredGene(AGG_GENE_KEY, PATH_A, 'FAP'))
    expect(result.current[0]).toBe('FAP')
  })

  it('restores a value that was stored for this dataset', () => {
    sessionStorage.setItem(storedGeneKey(AGG_GENE_KEY, PATH_A), 'EGFR')
    const { result } = renderHook(() => useStoredGene(AGG_GENE_KEY, PATH_A, 'FAP'))
    expect(result.current[0]).toBe('EGFR')
  })

  it("does not read another dataset's stored value", () => {
    sessionStorage.setItem(storedGeneKey(AGG_GENE_KEY, PATH_A), 'EGFR')
    const { result } = renderHook(() => useStoredGene(AGG_GENE_KEY, PATH_B, 'FAP'))
    expect(result.current[0]).toBe('FAP')
  })

  it('persists a chosen gene under this dataset only', () => {
    const { result } = renderHook(() => useStoredGene(AGG_GENE_KEY, PATH_A, 'FAP'))
    act(() => result.current[1]('COL1A1'))
    expect(stored(storedGeneKey(AGG_GENE_KEY, PATH_A))).toBe('COL1A1')
    expect(stored(storedGeneKey(AGG_GENE_KEY, PATH_B))).toBeNull()
  })

  it('adopts the new dataset instead of carrying the old gene across', () => {
    // AnalysisPage does not remount on a dataset switch, so the container
    // survives holding dataset A's gene. Writing it under B's key would move the
    // wrong gene into B and look like B's own remembered selection.
    const { result, rerender } = renderHook(
      ({ path }: { path: string }) => useStoredGene(AGG_GENE_KEY, path, 'FAP'),
      { initialProps: { path: PATH_A } },
    )
    act(() => result.current[1]('COL1A1'))
    rerender({ path: PATH_B })
    expect(result.current[0]).toBe('FAP')
    expect(stored(storedGeneKey(AGG_GENE_KEY, PATH_B))).not.toBe('COL1A1')
  })

  it('keeps the old dataset remembered when switching away from it', () => {
    const { result, rerender } = renderHook(
      ({ path }: { path: string }) => useStoredGene(AGG_GENE_KEY, path, 'FAP'),
      { initialProps: { path: PATH_A } },
    )
    act(() => result.current[1]('COL1A1'))
    rerender({ path: PATH_B })
    expect(stored(storedGeneKey(AGG_GENE_KEY, PATH_A))).toBe('COL1A1')
  })

  it('does not write while the dataset path is still unknown', () => {
    // AnalysisPage reads its UMAP gene before realPath has loaded. Writing then
    // would blank the stored value with ''.
    sessionStorage.setItem(storedGeneKey(AGG_GENE_KEY, PATH_A), 'EGFR')
    const { result, rerender } = renderHook(
      ({ path }: { path: string }) => useStoredGene(AGG_GENE_KEY, path, ''),
      { initialProps: { path: '' } },
    )
    act(() => result.current[1]('CD3'))
    expect(stored(storedGeneKey(AGG_GENE_KEY, PATH_A))).toBe('EGFR')
    rerender({ path: PATH_A })
    expect(result.current[0]).toBe('EGFR')
  })

  it('readStoredGene returns the fallback when there is no dataset yet', () => {
    sessionStorage.setItem(storedGeneKey(AGG_GENE_KEY, ''), 'EGFR')
    expect(readStoredGene(AGG_GENE_KEY, '', 'FAP')).toBe('FAP')
  })

  it('keys two datasets apart', () => {
    expect(storedGeneKey(AGG_GENE_KEY, PATH_A)).not.toBe(storedGeneKey(AGG_GENE_KEY, PATH_B))
  })
})
