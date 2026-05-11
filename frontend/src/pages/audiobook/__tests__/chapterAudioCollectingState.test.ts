import { describe, expect, it } from 'vitest'

import {
  addCollectingChapterId,
  removeCollectingChapterId,
} from '../chapterAudioCollectingState'

describe('chapter audio collecting state', () => {
  it('adds and removes chapter ids without mutating the previous set', () => {
    const previous = new Set([1])

    const added = addCollectingChapterId(previous, 2)
    const removed = removeCollectingChapterId(added, 1)

    expect([...previous]).toEqual([1])
    expect([...added]).toEqual([1, 2])
    expect([...removed]).toEqual([2])
    expect(added.has(1)).toBe(true)
    expect(added.has(2)).toBe(true)
    expect(removed.has(1)).toBe(false)
  })
})
