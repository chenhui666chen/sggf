import { describe, expect, it } from 'vitest'

import { normalizeAITraceGenre } from '../aiTraceGenre'


describe('normalizeAITraceGenre', () => {
  it('maps project metadata to the backend genre vocabulary', () => {
    expect(normalizeAITraceGenre('Fantasy')).toBe('玄幻')
    expect(normalizeAITraceGenre('Romance')).toBe('言情')
    expect(normalizeAITraceGenre('sci-fi')).toBe('科幻')
    expect(normalizeAITraceGenre('武侠小说')).toBe('武侠')
  })

  it('keeps imports without a supported genre in automatic mode', () => {
    expect(normalizeAITraceGenre(null)).toBe('auto')
    expect(normalizeAITraceGenre('')).toBe('auto')
    expect(normalizeAITraceGenre('unknown')).toBe('auto')
  })
})
