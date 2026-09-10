import { describe, it, expect } from 'vitest'
import { deriveG2Op, mergeWarningText } from './mergeOp'

describe('deriveG2Op — which operator actually reaches the backend', () => {
  it('honours the applied operator only for a real merge of 2+ members', () => {
    expect(deriveG2Op('merge', 2, 'and')).toBe('and')
    expect(deriveG2Op('merge', 5, 'and')).toBe('and')
    expect(deriveG2Op('merge', 2, 'or')).toBe('or')
  })

  it('falls back to or outside a real merge, keeping those URLs unchanged', () => {
    // single-gene mode never merges
    expect(deriveG2Op('single', 3, 'and')).toBe('or')
    // no members → no gene2 param is sent at all
    expect(deriveG2Op('merge', 0, 'and')).toBe('or')
    // one member → backend falls back to a real per-gene row; the op cannot change it
    expect(deriveG2Op('merge', 1, 'and')).toBe('or')
  })
})

describe('mergeWarningText — telling the user which members were dropped', () => {
  it('stays silent when every member resolved', () => {
    expect(mergeWarningText({ unresolved: [], resolved: ['COL1A1', 'COL1A2'], op: 'and' })).toBeNull()
    expect(mergeWarningText({ unresolved: [], resolved: [], op: 'or' })).toBeNull()
  })

  it('names every missing member and states the operator actually used', () => {
    expect(mergeWarningText({ unresolved: ['NOPE'], resolved: ['COL1A1', 'COL1A2'], op: 'and' }))
      .toBe('未找到 NOPE；已按 2 个基因取交集')
    expect(mergeWarningText({ unresolved: ['NOPE'], resolved: ['COL1A1', 'COL1A2'], op: 'or' }))
      .toBe('未找到 NOPE；已按 2 个基因取并集')
    expect(mergeWarningText({ unresolved: ['A', 'B'], resolved: ['COL1A1', 'COL1A2'], op: 'and' }))
      .toBe('未找到 A、B；已按 2 个基因取交集')
  })

  it('summarises a long list of missing members instead of overflowing the panel', () => {
    expect(mergeWarningText({ unresolved: ['A', 'B', 'C', 'D', 'E'], resolved: [], op: 'or' }))
      .toBe('未找到 A、B、C 等 5 个；未合并出合成基因，表中只有主基因')
  })

  it('flags the degenerate single-member case, where M stops being a boolean', () => {
    // The backend then emits a real per-gene row with a continuous mean, not the
    // 0/1 the user asked for — worth spelling out rather than showing a count.
    expect(mergeWarningText({ unresolved: ['NOPE'], resolved: ['COL1A1'], op: 'and' }))
      .toBe('未找到 NOPE；已退化为单基因 COL1A1（不再合并）')
  })

  it('flags the case where nothing merged at all', () => {
    expect(mergeWarningText({ unresolved: ['NOPE'], resolved: [], op: 'and' }))
      .toBe('未找到 NOPE；未合并出合成基因，表中只有主基因')
  })
})
