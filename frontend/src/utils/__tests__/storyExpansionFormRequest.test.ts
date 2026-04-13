import { describe, expect, it } from 'vitest'

import type { StoryExpansionDialogFormState } from '@/types/storyExpansionDialog'
import { createStoryExpansionRequestPayloadFromForm } from '../storyExpansionFormRequest'

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

describe('storyExpansionFormRequest', () => {
  it('uses direct form targets when analysis is not preferred', () => {
    expect(
      createStoryExpansionRequestPayloadFromForm({
        projectId: 7,
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
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
          effective_target_chapter_count: 60,
          effective_target_character_count: 12,
        },
        preferAnalysis: false,
      }),
    ).toMatchObject({
      target_total_chapters: 36,
      target_total_characters: 8,
      strategy: 'balanced',
      intent: 'character_led',
    })
  })

  it('omits total chapter target for volume detail payloads', () => {
    expect(
      createStoryExpansionRequestPayloadFromForm({
        projectId: 8,
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
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
        preferAnalysis: true,
      }),
    ).toMatchObject({
      expansion_mode: 'volume_detail',
      target_total_chapters: undefined,
      target_total_characters: 22,
      target_volume_index: 3,
    })
  })

  it('长篇框架分析请求会忽略表单中残留的人物目标值', () => {
    expect(
      createStoryExpansionRequestPayloadFromForm({
        projectId: 9,
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 80,
        currentCharacterCount: 12,
        form: createBaseForm({
          expansionMode: 'epic_framework',
          targetChapterCount: null,
          targetCharacterCount: 220,
          totalVolumes: 12,
          totalChaptersMin: 800,
          totalChaptersMax: 1200,
        }),
        requestControls: {
          strategy: 'auto',
          intent: 'outline_led',
        },
        preferAnalysis: false,
      }),
    ).toMatchObject({
      expansion_mode: 'epic_framework',
      target_total_chapters: 1200,
      target_total_characters: undefined,
    })
  })

  it('长篇框架正式提交时会采用分析返回的框架阶段人物目标', () => {
    expect(
      createStoryExpansionRequestPayloadFromForm({
        projectId: 10,
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 80,
        currentCharacterCount: 12,
        form: createBaseForm({
          expansionMode: 'epic_framework',
          targetChapterCount: null,
          targetCharacterCount: 220,
          totalVolumes: 12,
          totalChaptersMin: 800,
          totalChaptersMax: 1200,
        }),
        requestControls: {
          strategy: 'auto',
          intent: 'outline_led',
        },
        analysis: {
          effective_target_chapter_count: 1200,
          effective_target_character_count: 34,
        },
        preferAnalysis: true,
      }),
    ).toMatchObject({
      expansion_mode: 'epic_framework',
      target_total_chapters: 1200,
      target_total_characters: 34,
    })
  })
})
