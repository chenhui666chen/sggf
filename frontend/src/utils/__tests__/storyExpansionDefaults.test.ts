import { describe, expect, it } from 'vitest'

import {
  getPreferredStoryVolumeIndex,
  resolveStoryExpansionDialogDefaults,
  resolveStoryExpansionDefaults,
  resolveStoryExpansionModeDefaults,
  resolveStoryExpansionRequestControls,
} from '../storyExpansionDefaults'

describe('storyExpansionDefaults', () => {
  it('优先选择第一个未展开的卷号', () => {
    expect(
      getPreferredStoryVolumeIndex({
        has_framework: true,
        metadata: {
          total_volumes: 5,
          expanded_volumes: [1, 2, 4],
        },
      }),
    ).toBe(3)
  })

  it('当所有卷都已展开时回退到最后一个已展开卷', () => {
    expect(
      getPreferredStoryVolumeIndex({
        has_framework: true,
        metadata: {
          total_volumes: 3,
          expanded_volumes: [1, 2, 3],
        },
      }),
    ).toBe(3)
  })

  it('已有长篇框架时无论入口如何都默认切到单卷细化协同', () => {
    expect(
      resolveStoryExpansionDefaults({
        entryPoint: 'character',
        recommendedMode: 'epic_framework',
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 6,
            expanded_volumes: [1, 2, 3],
          },
        },
        currentChapterCount: 42,
        currentCharacterCount: 9,
      }),
    ).toEqual({
      expansionMode: 'volume_detail',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 4,
    })
  })

  it('人物入口在无框架时保持常规协同并补人物目标', () => {
    expect(
      resolveStoryExpansionDefaults({
        entryPoint: 'character',
        recommendedMode: 'epic_framework',
        frameworkMetadata: null,
        currentChapterCount: 18,
        currentCharacterCount: 5,
      }),
    ).toEqual({
      expansionMode: 'total',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 1,
    })
  })

  it('弹窗默认值会基于推荐结果重置整套协同配置', () => {
    expect(
      resolveStoryExpansionDialogDefaults({
        entryPoint: 'outline',
        recommendedMode: 'epic_framework',
        recommendedVolumes: 8,
        recommendedChaptersPerVolumeMin: 60,
        recommendedChaptersPerVolumeMax: 80,
        frameworkMetadata: null,
        currentChapterCount: 42,
        currentCharacterCount: 9,
      }),
    ).toEqual({
      expansionMode: 'epic_framework',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 1,
      totalVolumes: 8,
      totalChaptersMin: 480,
      totalChaptersMax: 640,
      volumeChaptersMin: 60,
      volumeChaptersMax: 80,
      volumeCharacterIncrement: null,
    })
  })

  it('已有框架时弹窗默认值仍会重置为单卷细化而不是复用旧输入', () => {
    expect(
      resolveStoryExpansionDialogDefaults({
        entryPoint: 'character',
        recommendedMode: 'epic_framework',
        recommendedVolumes: 12,
        recommendedChaptersPerVolumeMin: 50,
        recommendedChaptersPerVolumeMax: 70,
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 5,
            expanded_volumes: [1, 2, 4],
          },
        },
        currentChapterCount: 80,
        currentCharacterCount: 14,
      }),
    ).toEqual({
      expansionMode: 'volume_detail',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 3,
      totalVolumes: 12,
      totalChaptersMin: 600,
      totalChaptersMax: 840,
      volumeChaptersMin: 60,
      volumeChaptersMax: 80,
      volumeCharacterIncrement: null,
    })
  })

  it('模式切到长篇框架时会重置到该模式的干净默认态', () => {
    expect(
      resolveStoryExpansionModeDefaults({
        entryPoint: 'outline',
        mode: 'epic_framework',
        frameworkMetadata: null,
        currentChapterCount: 36,
        currentCharacterCount: 7,
        recommendedVolumes: 6,
        recommendedChaptersPerVolumeMin: 50,
        recommendedChaptersPerVolumeMax: 70,
      }),
    ).toEqual({
      expansionMode: 'epic_framework',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 1,
      totalVolumes: 6,
      totalChaptersMin: 300,
      totalChaptersMax: 420,
      volumeChaptersMin: 60,
      volumeChaptersMax: 80,
      volumeCharacterIncrement: null,
    })
  })

  it('模式切到常规协同时会按入口重置章节和人物目标', () => {
    expect(
      resolveStoryExpansionModeDefaults({
        entryPoint: 'character',
        mode: 'total',
        frameworkMetadata: null,
        currentChapterCount: 24,
        currentCharacterCount: 6,
        recommendedVolumes: 10,
        recommendedChaptersPerVolumeMin: 60,
        recommendedChaptersPerVolumeMax: 80,
      }),
    ).toEqual({
      expansionMode: 'total',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 1,
      totalVolumes: 30,
      totalChaptersMin: 2000,
      totalChaptersMax: 2500,
      volumeChaptersMin: 60,
      volumeChaptersMax: 80,
      volumeCharacterIncrement: null,
    })
  })

  it('模式切到单卷细化时会重置卷级配置并回到当前人物规模', () => {
    expect(
      resolveStoryExpansionModeDefaults({
        entryPoint: 'outline',
        mode: 'volume_detail',
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 5,
            expanded_volumes: [1, 2, 4],
          },
        },
        currentChapterCount: 96,
        currentCharacterCount: 12,
        recommendedVolumes: 9,
        recommendedChaptersPerVolumeMin: 55,
        recommendedChaptersPerVolumeMax: 75,
      }),
    ).toEqual({
      expansionMode: 'volume_detail',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 3,
      totalVolumes: 30,
      totalChaptersMin: 2000,
      totalChaptersMax: 2500,
      volumeChaptersMin: 60,
      volumeChaptersMax: 80,
      volumeCharacterIncrement: null,
    })
  })

  it('已有框架后仍允许主动切换回长篇框架协同重新生成', () => {
    expect(
      resolveStoryExpansionModeDefaults({
        entryPoint: 'outline',
        mode: 'epic_framework',
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 6,
            expanded_volumes: [1, 2, 3],
          },
        },
        currentChapterCount: 120,
        currentCharacterCount: 18,
        recommendedVolumes: 10,
        recommendedChaptersPerVolumeMin: 60,
        recommendedChaptersPerVolumeMax: 80,
      }),
    ).toEqual({
      expansionMode: 'epic_framework',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 1,
      totalVolumes: 10,
      totalChaptersMin: 600,
      totalChaptersMax: 800,
      volumeChaptersMin: 60,
      volumeChaptersMax: 80,
      volumeCharacterIncrement: null,
    })
  })

  it('大纲入口的协同控制值默认保持全自动', () => {
    expect(resolveStoryExpansionRequestControls('outline')).toEqual({
      strategy: 'auto',
      intent: 'auto',
    })
  })

  it('人物入口的协同控制值默认保持全自动', () => {
    expect(resolveStoryExpansionRequestControls('character')).toEqual({
      strategy: 'auto',
      intent: 'auto',
    })
  })
})
