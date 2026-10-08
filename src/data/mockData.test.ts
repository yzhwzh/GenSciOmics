import { describe, it, expect } from 'vitest'
import { ORGAN_SHAPES } from './mockData'
import { SPECIES_ORGANS } from './organShapes'

/**
 * In SVG path grammar a comma separates *values*, never commands — the only
 * legal separator before a command letter is whitespace (or the start of the
 * string). So `...933.912z,M464.609,920.76...` makes the browser report
 * "Expected path command" and DROP everything after the comma, silently: the
 * organ still renders, just with only its first lobe. Found on the Kidney and
 * Adrenal Gland shapes 2026-10-08 (two console errors, no visible failure).
 */
const COMMA_BEFORE_COMMAND = /,[ \t\r\n]*[MmZzLlHhVvCcSsQqTtAa]/

const BODY_MAP_SHAPES = [...ORGAN_SHAPES, ...Object.values(SPECIES_ORGANS).flat()]

describe('body map organ paths', () => {
  it('never separates two path commands with a comma', () => {
    const offenders = BODY_MAP_SHAPES.flatMap((organ) =>
      organ.paths
        .filter((d) => COMMA_BEFORE_COMMAND.test(d))
        .map((d) => {
          const at = d.search(COMMA_BEFORE_COMMAND)
          return `${organ.slug}: ...${d.slice(Math.max(0, at - 12), at + 3)}...`
        }),
    )

    expect(offenders).toEqual([])
  })

  it('still joins subpaths with "z" followed by a command, rather than dropping the lobe', () => {
    // Two subpaths are joined by "z" followed by the next moveto. Asserting
    // only that a second "M" exists somewhere in the string would pass even
    // with the broken "z,M", because the letter is in the source — it is the
    // browser that discards it, so assert the join itself. Whitespace is a
    // legal separator and is what the fix uses ("z M"); a comma is not, so
    // \s* still rejects the broken form. This also fails if someone "fixes" a
    // comma by deleting the second lobe.
    for (const slug of ['kidney', 'adrenal_gland']) {
      const organ = ORGAN_SHAPES.find((o) => o.slug === slug)
      expect(organ, `${slug} is missing from the body map`).toBeDefined()

      const joined = organ!.paths.join(' ')
      expect(joined, `${slug} lost its second subpath`).toMatch(/[zZ]\s*[Mm]/)
    }
  })
})
