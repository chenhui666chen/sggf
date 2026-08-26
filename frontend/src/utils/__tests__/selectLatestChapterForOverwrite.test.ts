import { describe, expect, it } from 'vitest'
import { selectLatestChapterForOverwrite } from '../selectLatestChapterForOverwrite'

describe('selectLatestChapterForOverwrite', () => {
  it('returns the chapter with the highest chapter_number', () => {
    expect(
      selectLatestChapterForOverwrite([
        { id: 26, chapter_number: 26 },
        { id: 27, chapter_number: 27 },
        { id: 25, chapter_number: 25 },
      ]),
    ).toEqual({ id: 27, chapter_number: 27 })
  })

  it('returns null when there is no existing chapter to overwrite', () => {
    expect(selectLatestChapterForOverwrite([])).toBeNull()
    expect(selectLatestChapterForOverwrite(undefined)).toBeNull()
  })
})