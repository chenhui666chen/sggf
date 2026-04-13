import { describe, expect, it } from 'vitest'

import type { StoryExpansionDialogFormState } from '@/types/storyExpansionDialog'
import {
  confirmStoryExpansionSubmitPreflight,
  createStoryExpansionSubmitPayload,
  createStoryExpansionSubmitPreflight,
  getStoryExpansionFrameworkResetConfirmMessage,
  getStoryExpansionVolumeOverwriteConfirmMessage,
} from '../storyExpansionSubmission'

function createBaseForm(overrides: Partial<StoryExpansionDialogFormState> = {}): StoryExpansionDialogFormState {
  return {
    targetChapterCount: 24,
    targetCharacterCount: 6,
    expansionMode: 'total',
    totalVolumes: 8,
    totalChaptersMin: 600,
    totalChaptersMax: 900,
    frameworkMetadata: null,
    targetVolumeIndex: 2,
    volumeChaptersMin: 30,
    volumeChaptersMax: 40,
    volumeCharacterIncrement: 2,
    autoSupplementEnabled: true,
    preserveWrittenMode: 'extract_extend',
    ...overrides,
  }
}

describe('storyExpansionSubmission', () => {
  it('returns validation error when story context is missing', () => {
    expect(
      createStoryExpansionSubmitPreflight({
        content: {
          worldSetting: '',
          plotOutline: '',
          characters: '',
        },
        currentChapterCount: 12,
        currentCharacterCount: 4,
        form: createBaseForm(),
      }).validationError,
    ).toBe('请先准备好世界观和情节大纲，再执行协同扩展')
  })

  it('requests overwrite confirmation for expanded volume regeneration', () => {
    expect(
      createStoryExpansionSubmitPreflight({
        content: {
          worldSetting: '世界观',
          plotOutline: '大纲',
          characters: '人物',
        },
        currentChapterCount: 80,
        currentCharacterCount: 10,
        form: createBaseForm({
          expansionMode: 'volume_detail',
          frameworkMetadata: {
            has_framework: true,
            metadata: {
              total_volumes: 5,
              expanded_volumes: [1, 2],
            },
          },
          targetVolumeIndex: 2,
          targetChapterCount: null,
          targetCharacterCount: 10,
          volumeCharacterIncrement: null,
        }),
      }),
    ).toMatchObject({
      validationError: null,
      requiresVolumeOverwriteConfirm: true,
      volumeOverwriteConfirmMessage: getStoryExpansionVolumeOverwriteConfirmMessage(2),
      requiresResetFrameworkConfirm: false,
      resetFrameworkConfirmMessage: '',
    })
  })

  it('requests framework reset confirmation for regular chapter expansion', () => {
    expect(
      createStoryExpansionSubmitPreflight({
        content: {
          worldSetting: '世界观',
          plotOutline: '大纲',
          characters: '人物',
        },
        currentChapterCount: 20,
        currentCharacterCount: 5,
        form: createBaseForm({
          frameworkMetadata: {
            has_framework: true,
          },
          targetChapterCount: 30,
          targetCharacterCount: 5,
        }),
      }),
    ).toMatchObject({
      validationError: null,
      requiresVolumeOverwriteConfirm: false,
      volumeOverwriteConfirmMessage: '',
      requiresResetFrameworkConfirm: true,
      resetFrameworkConfirmMessage: getStoryExpansionFrameworkResetConfirmMessage(),
    })
  })

  it('runs confirmations in order before submit', () => {
    const confirmMessages: string[] = []
    const result = confirmStoryExpansionSubmitPreflight({
      requiresVolumeOverwriteConfirm: true,
      volumeOverwriteConfirmMessage: getStoryExpansionVolumeOverwriteConfirmMessage(2),
      requiresResetFrameworkConfirm: true,
      resetFrameworkConfirmMessage: getStoryExpansionFrameworkResetConfirmMessage(),
    }, (message) => {
      confirmMessages.push(message)
      return true
    })

    expect(result).toBe(true)
    expect(confirmMessages).toEqual([
      getStoryExpansionVolumeOverwriteConfirmMessage(2),
      getStoryExpansionFrameworkResetConfirmMessage(),
    ])
  })

  it('stops follow-up confirmations after cancellation', () => {
    const confirmMessages: string[] = []
    const result = confirmStoryExpansionSubmitPreflight({
      requiresVolumeOverwriteConfirm: true,
      volumeOverwriteConfirmMessage: getStoryExpansionVolumeOverwriteConfirmMessage(3),
      requiresResetFrameworkConfirm: true,
      resetFrameworkConfirmMessage: getStoryExpansionFrameworkResetConfirmMessage(),
    }, (message) => {
      confirmMessages.push(message)
      return false
    })

    expect(result).toBe(false)
    expect(confirmMessages).toEqual([
      getStoryExpansionVolumeOverwriteConfirmMessage(3),
    ])
  })

  it('builds payload with analysis overrides', () => {
    expect(
      createStoryExpansionSubmitPayload({
        projectId: 9,
        content: {
          worldSetting: '世界观',
          plotOutline: '大纲',
          characters: '人物',
        },
        currentChapterCount: 20,
        currentCharacterCount: 5,
        form: createBaseForm({
          targetChapterCount: 36,
          targetCharacterCount: 8,
        }),
        requestControls: {
          strategy: 'auto',
          intent: 'outline_led',
        },
        analysis: {
          effective_strategy: 'balanced',
          effective_intent: 'character_led',
          effective_target_chapter_count: 40,
          effective_target_character_count: 9,
        },
      }),
    ).toMatchObject({
      project_id: 9,
      current_outline: '大纲',
      world_setting: '世界观',
      characters: '人物',
      current_chapter_count: 20,
      current_character_count: 5,
      target_total_chapters: 40,
      target_total_characters: 9,
      strategy: 'balanced',
      intent: 'character_led',
      enable_auto_supplement: true,
      expansion_mode: 'total',
      preserve_written_mode: 'extract_extend',
    })
  })

  it('does not send total chapter target for volume detail mode', () => {
    expect(
      createStoryExpansionSubmitPayload({
        projectId: 12,
        content: {
          worldSetting: '世界观',
          plotOutline: '大纲',
          characters: '人物',
        },
        currentChapterCount: 120,
        currentCharacterCount: 18,
        form: createBaseForm({
          expansionMode: 'volume_detail',
          frameworkMetadata: {
            has_framework: true,
            metadata: {
              total_volumes: 6,
              expanded_volumes: [1, 2],
            },
          },
          targetChapterCount: null,
          targetCharacterCount: 18,
          targetVolumeIndex: 3,
          volumeCharacterIncrement: null,
        }),
        requestControls: {
          strategy: 'auto',
          intent: 'outline_led',
        },
        analysis: {
          effective_target_chapter_count: 300,
          effective_target_character_count: 22,
        },
      }),
    ).toMatchObject({
      expansion_mode: 'volume_detail',
      target_total_chapters: undefined,
      target_total_characters: 22,
      target_volume_index: 3,
    })
  })
})
