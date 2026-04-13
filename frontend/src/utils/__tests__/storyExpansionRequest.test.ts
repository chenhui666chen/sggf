import { describe, expect, it } from 'vitest'

import {
  buildStoryExpansionRequestPayload,
  resolveStoryExpansionRequestTargets,
} from '../storyExpansionRequest'

describe('storyExpansionRequest', () => {
  it('常规协同只带通用字段', () => {
    expect(
      buildStoryExpansionRequestPayload({
        projectId: 1,
        currentOutline: '第1章：开场',
        worldSetting: '蒸汽仙侠世界',
        characters: '林舟',
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
      current_outline: '第1章：开场',
      world_setting: '蒸汽仙侠世界',
      characters: '林舟',
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

  it('长篇框架协同带上总卷与总章范围', () => {
    expect(
      buildStoryExpansionRequestPayload({
        projectId: 2,
        currentOutline: '',
        worldSetting: '玄幻世界',
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

  it('单卷细化协同带上卷级参数与人物增量', () => {
    expect(
      buildStoryExpansionRequestPayload({
        projectId: 3,
        currentOutline: '## 分卷概要',
        worldSetting: '都市异能',
        characters: '顾晚',
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

  it('分析阶段默认使用请求计划中的目标值', () => {
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

  it('正式提交阶段优先使用分析返回的有效目标', () => {
    expect(
      resolveStoryExpansionRequestTargets({
        currentChapterCount: 20,
        currentCharacterCount: 5,
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

  it('正式提交阶段在单卷细化下不会误带章节总目标', () => {
    expect(
      resolveStoryExpansionRequestTargets({
        currentChapterCount: 120,
        currentCharacterCount: 18,
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
})
