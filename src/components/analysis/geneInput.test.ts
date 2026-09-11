import { describe, it, expect, vi } from 'vitest'
import { exactGeneMatch, resolveGeneChoice, unknownGeneMessage, resolvedGeneMessage } from './geneInput'

/**
 * The three gene boxes are plain text inputs whose dropdown is a hint, not a
 * constraint: Enter and — worse — blur commit whatever is in the box. The
 * backend then resolved an unknown token by substring (server/analysis/utils.py:124)
 * and reported it as resolved. Measured against the live Lung IPF dataset
 * (33,694 genes): "CD3" -> "ABCD3", "COL1" -> "COL16A1", "A1" -> "VWA1".
 * Nothing downstream can catch that, so the check has to happen here.
 */
describe('exactGeneMatch', () => {
  const GENES = ['EGFR', 'EGF', 'EGR1', 'COL16A1', 'COL1A1', 'ABCD3', 'VWA1']

  it('returns the canonical spelling when only the case differs', () => {
    expect(exactGeneMatch('egfr', GENES)).toBe('EGFR')
  })

  it('ignores surrounding whitespace', () => {
    expect(exactGeneMatch('  EGFR  ', GENES)).toBe('EGFR')
  })

  // The regression: a typed prefix used to become a real gene downstream.
  it('refuses a prefix that is not itself a gene', () => {
    expect(exactGeneMatch('EG', GENES)).toBeNull()
    expect(exactGeneMatch('COL1', GENES)).toBeNull()
  })

  it('refuses a token that is merely contained in a gene', () => {
    expect(exactGeneMatch('CD3', GENES)).toBeNull()
    expect(exactGeneMatch('A1', GENES)).toBeNull()
  })

  it('refuses everything when nothing matches', () => {
    expect(exactGeneMatch('NOTAGENE', GENES)).toBeNull()
  })

  it('ignores blank input rather than matching the first gene', () => {
    expect(exactGeneMatch('', GENES)).toBeNull()
    expect(exactGeneMatch('   ', GENES)).toBeNull()
  })
})

describe('resolveGeneChoice', () => {
  const GENES = ['EGFR', 'EGF', 'EGR1']
  const never = vi.fn(() => Promise.resolve([] as string[]))

  it('commits from the listed suggestions without asking the server', async () => {
    const search = vi.fn(never)
    await expect(resolveGeneChoice('egfr', GENES, search)).resolves.toEqual({ kind: 'commit', gene: 'EGFR' })
    expect(search).not.toHaveBeenCalled()
  })

  // The suggestion list is debounced by 200ms, so a gene typed in one go is
  // usually not in it yet. Refusing on that basis would reject real genes.
  it('asks the server when the listed suggestions are stale', async () => {
    const search = vi.fn(() => Promise.resolve(['EGFR', 'EGF']))
    await expect(resolveGeneChoice('EGFR', [], search)).resolves.toEqual({ kind: 'commit', gene: 'EGFR' })
    expect(search).toHaveBeenCalledWith('EGFR')
  })

  it('rejects a prefix and hands back what the server did match', async () => {
    const search = vi.fn(() => Promise.resolve(['EGFR', 'EGF', 'EGR1']))
    await expect(resolveGeneChoice('EG', [], search)).resolves.toEqual({
      kind: 'reject',
      typed: 'EG',
      suggestions: ['EGFR', 'EGF', 'EGR1'],
    })
  })

  // A failed lookup must not fall through to committing the raw text — that is
  // the whole bug.
  it('rejects without committing when the lookup fails', async () => {
    const search = vi.fn(() => Promise.reject(new Error('offline')))
    await expect(resolveGeneChoice('EGFR', [], search)).resolves.toEqual({
      kind: 'reject',
      typed: 'EGFR',
      suggestions: [],
    })
  })

  it('ignores blank input', async () => {
    const search = vi.fn(never)
    await expect(resolveGeneChoice('   ', GENES, search)).resolves.toEqual({ kind: 'ignore' })
    expect(search).not.toHaveBeenCalled()
  })
})

describe('unknownGeneMessage', () => {
  // Names the offending text: "a gene was not found" alone leaves the reader
  // hunting for which box they mistyped.
  it('names the token that was rejected', () => {
    expect(unknownGeneMessage('CD3')).toContain('CD3')
  })
})

/**
 * The rejection above is the frontend's own guard, and it only covers the path
 * where the user *types* the box. A gene restored from storage — or typed into
 * a box that has no guard, like UMAP's — reaches the backend unchecked, where
 * the same substring fallback quietly returns a different gene. The plot then
 * looks completely normal. This is the only thing that tells the reader which
 * gene they are actually looking at.
 */
describe('resolvedGeneMessage', () => {
  it('warns with both names when the backend substituted another gene', () => {
    const msg = resolvedGeneMessage('CD3', 'ABCD3')
    expect(msg).toContain('CD3')
    expect(msg).toContain('ABCD3')
  })

  it('stays quiet when the backend used the gene as typed', () => {
    expect(resolvedGeneMessage('EGFR', 'EGFR')).toBe('')
  })

  // Typing "egfr" and being shown "EGFR" is the box doing its job — warning
  // about it would train the reader to ignore the line that matters.
  it('stays quiet when only the letter case differs', () => {
    expect(resolvedGeneMessage('egfr', 'EGFR')).toBe('')
  })

  // Responses cached before this field existed have no gene_resolved at all.
  // Absent means "backend did not say", not "backend substituted".
  it('stays quiet when the response predates the field', () => {
    expect(resolvedGeneMessage('EGFR', undefined)).toBe('')
    expect(resolvedGeneMessage('EGFR', '')).toBe('')
  })
})
