import { describe, expect, it } from 'vitest'

import {
  buildStoryExpansionRequestPayload,
  resolveStoryExpansionRequestTargets,
} from '../storyExpansionRequest'

describe('storyExpansionRequest', () => {
  it('builds a total-mode payload with shared fields only', () => {
    expect(
      buildStoryExpansionRequestPayload({
        projectId: 1,
        currentOutline: 'Chapter 1: Opening',
        worldSetting: 'Steam fantasy world',
        characters: 'Lin Zhou',
        currentChapterCount: 10,
        currentCharacterCount: 3,
        targetTotalChapters: 18,
        targetTotalCharacters: 5,
        strategy: 'auto',
        intent: 'outline_led',
        enableAutoSupplement: true,
        expansionMode: 'total',
        totalVolumes: 12,
        totalChaptersMin: 500,
        totalChaptersMax: 800,
        targetVolumeIndex: 2,
        volumeChaptersMin: 30,
        volumeChaptersMax: 40,
        volumeCharacterIncrement: 3,
        preserveWrittenMode: 'extract_extend',
        resetEpicFramework: false,
      }),
    ).toEqual({
      project_id: 1,
      current_outline: 'Chapter 1: Opening',
      world_setting: 'Steam fantasy world',
      characters: 'Lin Zhou',
      current_chapter_count: 10,
      current_character_count: 3,
      target_total_chapters: 18,
      target_total_characters: 5,
      strategy: 'auto',
      intent: 'outline_led',
      enable_auto_supplement: true,
      expansion_mode: 'total',
      preserve_written_mode: 'extract_extend',
      reset_epic_framework: undefined,
    })
  })

  it('adds epic framework range fields to epic payloads', () => {
    expect(
      buildStoryExpansionRequestPayload({
        projectId: 2,
        currentOutline: '',
        worldSetting: 'Fantasy world',
        characters: '',
        currentChapterCount: 40,
        currentCharacterCount: 8,
        strategy: 'balanced',
        intent: 'balanced',
        enableAutoSupplement: true,
        expansionMode: 'epic_framework',
        totalVolumes: 10,
        totalChaptersMin: 600,
        totalChaptersMax: 900,
        preserveWrittenMode: 'preserve_written',
      }),
    ).toMatchObject({
      expansion_mode: 'epic_framework',
      total_volumes: 10,
      total_chapters_min: 600,
      total_chapters_max: 900,
    })
  })

  it('adds volume detail fields and character increment to volume payloads', () => {
    expect(
      buildStoryExpansionRequestPayload({
        projectId: 3,
        currentOutline: '## Volume Summary',
        worldSetting: 'Urban supernatural',
        characters: 'Gu Wan',
        currentChapterCount: 60,
        currentCharacterCount: 9,
        strategy: 'plot_first',
        intent: 'character_led',
        enableAutoSupplement: false,
        expansionMode: 'volume_detail',
        targetVolumeIndex: 4,
        volumeChaptersMin: 30,
        volumeChaptersMax: 40,
        volumeCharacterIncrement: 2,
        preserveWrittenMode: 'extract_extend',
        resetEpicFramework: true,
      }),
    ).toMatchObject({
      expansion_mode: 'volume_detail',
      target_volume_index: 4,
      volume_chapters_min: 30,
      volume_chapters_max: 40,
      volume_character_increment: 2,
      reset_epic_framework: true,
    })
  })

  it('uses planned request targets when analysis is not preferred', () => {
    expect(
      resolveStoryExpansionRequestTargets({
        currentChapterCount: 20,
        currentCharacterCount: 5,
        requestPlan: {
          isVolumeDetailMode: false,
          requestedTargetChapterCount: 36,
          requestedTargetCharacterCount: 8,
          requestedChapterDelta: 16,
          requestedCharacterDelta: 3,
        },
      }),
    ).toEqual({
      targetTotalChapters: 36,
      targetTotalCharacters: 8,
    })
  })

  it('prefers analysis targets when the user explicitly provided both fields', () => {
    expect(
      resolveStoryExpansionRequestTargets({
        currentChapterCount: 20,
        currentCharacterCount: 5,
        expansionMode: 'total',
        preferAnalysis: true,
        requestPlan: {
          isVolumeDetailMode: false,
          requestedTargetChapterCount: 36,
          requestedTargetCharacterCount: 8,
          requestedChapterDelta: 16,
          requestedCharacterDelta: 3,
        },
        analysis: {
          effective_target_chapter_count: 40,
          effective_target_character_count: 9,
        },
      }),
    ).toEqual({
      targetTotalChapters: 40,
      targetTotalCharacters: 9,
    })
  })

  it('keeps the character target blank when phased total-mode auto supplement should continue on the server', () => {
    expect(
      resolveStoryExpansionRequestTargets({
        currentChapterCount: 20,
        currentCharacterCount: 7,
        expansionMode: 'total',
        preferAnalysis: true,
        requestPlan: {
          isVolumeDetailMode: false,
          requestedTargetChapterCount: 300,
          requestedTargetCharacterCount: undefined,
          requestedChapterDelta: 280,
          requestedCharacterDelta: 0,
        },
        analysis: {
          effective_target_chapter_count: 300,
          effective_target_character_count: 15,
          effective_expansion_mode: 'total',
          auto_supplement: {
            character_delta: 8,
            character_plan: {
              stage_target_characters: 15,
              task_target_characters: 35,
            },
          },
        },
      }),
    ).toEqual({
      targetTotalChapters: 300,
      targetTotalCharacters: undefined,
    })
  })

  it('still omits total chapter target for volume detail mode', () => {
    expect(
      resolveStoryExpansionRequestTargets({
        currentChapterCount: 120,
        currentCharacterCount: 18,
        expansionMode: 'volume_detail',
        preferAnalysis: true,
        requestPlan: {
          isVolumeDetailMode: true,
          requestedTargetChapterCount: undefined,
          requestedTargetCharacterCount: 24,
          requestedChapterDelta: 0,
          requestedCharacterDelta: 6,
        },
        analysis: {
          effective_target_chapter_count: 200,
          effective_target_character_count: null,
        },
      }),
    ).toEqual({
      targetTotalChapters: undefined,
      targetTotalCharacters: 24,
    })
  })

  it('uses analysis character target for volume detail mode when the form leaves characters blank', () => {
    expect(
      resolveStoryExpansionRequestTargets({
        currentChapterCount: 120,
        currentCharacterCount: 18,
        expansionMode: 'volume_detail',
        preferAnalysis: true,
        requestPlan: {
          isVolumeDetailMode: true,
          requestedTargetChapterCount: undefined,
          requestedTargetCharacterCount: undefined,
          requestedChapterDelta: 0,
          requestedCharacterDelta: 0,
        },
        analysis: {
          effective_target_chapter_count: 200,
          effective_target_character_count: 22,
          volume_detail: {
            character_increment: 4,
            target_character_count: 22,
          },
        },
      }),
    ).toEqual({
      targetTotalChapters: undefined,
      targetTotalCharacters: 22,
    })
  })
})
