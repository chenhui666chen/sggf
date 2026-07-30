import { describe, expect, it } from 'vitest'

import {
  buildScriptCompletionSummary,
  hasPlayableChapterAudio,
  resolveAudiobookCompletionMode,
  resolveScriptReviewTargetChapterId,
  resolveScriptStatusPresentation,
} from '../completionViewUtils'
import type { ChapterAudio } from '../types'

const chapterAudios: ChapterAudio[] = [
  {
    id: 1,
    chapter_id: 11,
    has_script: true,
    has_review: true,
    script_status: 'approved',
    segment_count: 18,
    dialogue_count: 8,
    narration_count: 10,
    character_count: 3,
  },
  {
    id: 2,
    chapter_id: 12,
    has_script: true,
    has_review: true,
    script_status: 'reviewed',
    segment_count: 12,
    dialogue_count: 7,
    narration_count: 5,
    character_count: 2,
  },
  {
    id: 3,
    chapter_id: 13,
    has_script: true,
    script_status: 'pending',
    segment_count: 6,
  },
]

describe('audiobook completion view utils', () => {
  it('distinguishes script rows from playable chapter audio', () => {
    expect(hasPlayableChapterAudio(chapterAudios)).toBe(false)
    expect(hasPlayableChapterAudio([
      ...chapterAudios,
      { id: 4, chapter_id: 14, audio_path: '/audio/chapter-14.mp3' },
    ])).toBe(true)
  })

  it('recovers the script completion mode when a refreshed project has scripts but no audio', () => {
    expect(resolveAudiobookCompletionMode({
      requestedMode: 'full',
      chapterAudios,
    })).toBe('script_only')
    expect(resolveAudiobookCompletionMode({
      requestedMode: 'full',
      chapterAudios: [{ id: 4, chapter_id: 14, audio_path: '/audio/chapter-14.mp3' }],
    })).toBe('full')
    expect(resolveAudiobookCompletionMode({
      requestedMode: 'script_only',
      chapterAudios: [{ id: 4, chapter_id: 14, audio_path: '/audio/chapter-14.mp3' }],
    })).toBe('script_only')
  })

  it('summarizes only script-stage facts', () => {
    expect(buildScriptCompletionSummary(chapterAudios)).toEqual({
      scriptChapterCount: 3,
      segmentCount: 36,
      reviewedChapterCount: 2,
      approvedChapterCount: 1,
      pendingApprovalCount: 2,
    })
  })

  it('targets the first unapproved script and falls back to the first script', () => {
    expect(resolveScriptReviewTargetChapterId(chapterAudios)).toBe(12)
    expect(resolveScriptReviewTargetChapterId([
      { id: 1, chapter_id: 11, has_script: true, script_status: 'approved' },
      { id: 2, chapter_id: 12, has_script: true, script_status: 'approved' },
    ])).toBe(11)
    expect(resolveScriptReviewTargetChapterId([])).toBeNull()
  })

  it('uses approval-oriented labels instead of audio status labels', () => {
    expect(resolveScriptStatusPresentation('approved').label).toBe('已批准')
    expect(resolveScriptStatusPresentation('reviewed').label).toBe('待确认批准')
    expect(resolveScriptStatusPresentation('pending').label).toBe('待审阅')
  })
})
