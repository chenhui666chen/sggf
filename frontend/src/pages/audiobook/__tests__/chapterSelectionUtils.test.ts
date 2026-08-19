import { describe, expect, it } from 'vitest'

import {
  normalizeSingleChapterSelection,
  resolveAudiobookProjectForChapter,
  resolveAudiobookProjectIdForChapter,
  resolveChapterStateById,
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

  it('resolves the audiobook project that owns a generated chapter', () => {
    const audiobookProjectId = resolveAudiobookProjectIdForChapter([
      { id: 11, chapter_audios: [{ id: 21, chapter_id: 1, has_script: true }] },
      { id: 12, chapter_audios: [{ id: 22, chapter_id: 2, audio_path: '/chapter-2.mp3' }] },
    ], 2)

    expect(audiobookProjectId).toBe(12)
    expect(resolveAudiobookProjectIdForChapter([], 2)).toBeNull()
  })

  it('prefers a published batch over newer batches for the same chapter (§2.5 rule 1)', () => {
    const selection = resolveAudiobookProjectForChapter([
      {
        id: 31,
        engine_mode: 'seed_scene',
        created_at: '2026-08-10T00:00:00Z',
        chapter_audios: [{ id: 41, chapter_id: 1, render_status: 'manual_review_required' }],
      },
      {
        id: 32,
        engine_mode: 'seed_scene',
        created_at: '2026-08-01T00:00:00Z',
        chapter_audios: [{ id: 42, chapter_id: 1, render_status: 'rendered_all_seed' }],
      },
    ], 1)

    expect(selection).toEqual({
      audiobookProjectId: 32,
      engineMode: 'seed_scene',
      renderStatus: 'rendered_all_seed',
    })
  })

  it('falls back to the newest batch when no published output exists (§2.5 rule 2)', () => {
    const selection = resolveAudiobookProjectForChapter([
      {
        id: 21,
        engine_mode: 'legacy_stems',
        created_at: '2026-07-01T00:00:00Z',
        chapter_audios: [{ id: 51, chapter_id: 2, audio_path: '/a.mp3' }],
      },
      {
        id: 22,
        engine_mode: 'legacy_stems',
        created_at: '2026-08-01T00:00:00Z',
        chapter_audios: [{ id: 52, chapter_id: 2, audio_path: '/b.mp3' }],
      },
    ], 2)

    expect(selection?.audiobookProjectId).toBe(22)
    expect(selection?.engineMode).toBe('legacy_stems')
    expect(selection?.renderStatus).toBeNull()
  })

  it('returns null when no batch owns the chapter', () => {
    expect(resolveAudiobookProjectForChapter([
      { id: 1, engine_mode: 'seed_scene', chapter_audios: [{ id: 2, chapter_id: 9 }] },
    ], 10)).toBeNull()
  })

  // 场景生成与分轨合成完全分离：当前批次引擎与视图引擎不一致时，
  // 当前批次的分轨产物不得计入已生成/锁定集合（防止未生成却被锁章）
  it('excludes legacy batch outputs from the seed_scene chapter state', () => {
    const stateById = resolveChapterStateById(
      [],
      'seed_scene',
      [{ id: 61, chapter_id: 1, audio_path: '/legacy/chapter-1.mp3', has_script: true }],
      null,
      'legacy_stems',
    )

    expect(stateById[1]).toBeUndefined()
  })

  it('keeps current batch outputs when engines match', () => {
    const stateById = resolveChapterStateById(
      [],
      'legacy_stems',
      [{ id: 62, chapter_id: 2, audio_path: '/legacy/chapter-2.mp3' }],
      null,
      'legacy_stems',
    )

    expect(stateById[2]?.exportable).toBe(true)
  })

  it('keeps the historical seed fallback for seed_scene batches without render_status', () => {
    const stateById = resolveChapterStateById(
      [{
        id: 71,
        engine_mode: 'seed_scene',
        chapter_audios: [{ id: 72, chapter_id: 3, audio_path: '/seed/chapter-3.mp3' }],
      }],
      'seed_scene',
      [],
    )

    expect(stateById[3]).toBeDefined()
    expect(stateById[3]?.renderStatus).toBeNull()
  })
})
