import { describe, expect, it } from 'vitest'

import {
  normalizeSingleChapterSelection,
  resolveGeneratedChapterIds,
  resolveGeneratedChapterIdsFromProjects,
  toggleSingleChapterSelection,
} from '../chapterSelectionUtils'
import type { Chapter, ChapterAudio } from '../types'


const chapters: Chapter[] = [
  { id: 1, chapter_number: 1, title: '第一章', content: '正文一' },
  { id: 2, chapter_number: 2, title: '第二章', content: '正文二' },
  { id: 3, chapter_number: 3, title: '第三章', content: '正文三' },
]


describe('audiobook chapter selection utils', () => {
  it('marks chapters with generated scripts or audio as locked', () => {
    const chapterAudios: ChapterAudio[] = [
      { id: 11, chapter_id: 1, has_script: true },
      { id: 12, chapter_id: 2, audio_path: '/audio/chapter-2.mp3' },
      { id: 13, chapter_id: 3, has_script: false, script_status: 'pending' },
      { id: 14, chapter_id: 4, script_status: 'approved' },
    ]

    expect([...resolveGeneratedChapterIds(chapterAudios)]).toEqual([1, 2, 4])
  })

  it('selects at most one unlocked chapter and ignores locked chapters', () => {
    const lockedChapterIds = new Set([1])

    expect(toggleSingleChapterSelection({
      selectedChapterIds: [2],
      chapterId: 3,
      lockedChapterIds,
    })).toEqual([3])
    expect(toggleSingleChapterSelection({
      selectedChapterIds: [2],
      chapterId: 2,
      lockedChapterIds,
    })).toEqual([2])
    expect(toggleSingleChapterSelection({
      selectedChapterIds: [2],
      chapterId: 1,
      lockedChapterIds,
    })).toEqual([2])
  })

  it('moves an invalid or locked selection to the first selectable chapter', () => {
    const lockedChapterIds = new Set([1, 2])

    expect(normalizeSingleChapterSelection({
      chapters,
      selectedChapterIds: [1, 2],
      lockedChapterIds,
    })).toEqual([3])
    expect(normalizeSingleChapterSelection({
      chapters,
      selectedChapterIds: [3, 2],
      lockedChapterIds,
    })).toEqual([3])
    expect(normalizeSingleChapterSelection({
      chapters: chapters.slice(0, 2),
      selectedChapterIds: [1],
      lockedChapterIds,
    })).toEqual([])
  })

  it('keeps generated chapters locked across audiobook project history', () => {
    const generatedChapterIds = resolveGeneratedChapterIdsFromProjects(
      [
        { chapter_audios: [{ id: 21, chapter_id: 1, has_script: true }] },
        { chapter_audios: [{ id: 22, chapter_id: 2, audio_path: '/chapter-2.mp3' }] },
      ],
      [{ id: 23, chapter_id: 3, has_script: true }],
    )

    expect([...generatedChapterIds]).toEqual([1, 2, 3])
  })
})
