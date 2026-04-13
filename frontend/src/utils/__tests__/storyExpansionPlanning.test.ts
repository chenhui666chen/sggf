import { describe, expect, it } from 'vitest'

import {
  buildStoryExpansionRequestPlan,
  getStoryExpansionValidationError,
  shouldConfirmStoryExpansionVolumeOverwrite,
} from '../storyExpansionPlanning'

describe('storyExpansionPlanning', () => {
  it('为常规协同推导目标、增量与框架重置标记', () => {
    expect(
      buildStoryExpansionRequestPlan({
        expansionMode: 'total',
        currentChapterCount: 20,
        currentCharacterCount: 6,
        targetChapterCount: 30,
        targetCharacterCount: 9,
        frameworkMetadata: {
          has_framework: true,
        },
      }),
    ).toEqual({
      isVolumeDetailMode: false,
      isEpicFrameworkConfigured: false,
      isVolumeDetailConfigured: false,
      hasDelta: true,
      requestedTargetChapterCount: 30,
      requestedTargetCharacterCount: 9,
      requestedChapterDelta: 10,
      requestedCharacterDelta: 3,
      requiresEpicFrameworkReset: true,
    })
  })

  it('为长篇框架协同使用总章节上限作为请求目标', () => {
    expect(
      buildStoryExpansionRequestPlan({
        expansionMode: 'epic_framework',
        currentChapterCount: 120,
        currentCharacterCount: 12,
        targetCharacterCount: 88,
        totalVolumes: 8,
        totalChaptersMin: 300,
        totalChaptersMax: 900,
      }),
    ).toMatchObject({
      isEpicFrameworkConfigured: true,
      hasDelta: true,
      requestedTargetChapterCount: 900,
      requestedTargetCharacterCount: undefined,
      requestedChapterDelta: 780,
      requestedCharacterDelta: 0,
    })
  })

  it('识别单卷细化是否已具备可提交配置', () => {
    expect(
      buildStoryExpansionRequestPlan({
        expansionMode: 'volume_detail',
        currentChapterCount: 80,
        currentCharacterCount: 14,
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 6,
          },
        },
        targetVolumeIndex: 4,
        volumeChaptersMin: 30,
        volumeChaptersMax: 45,
      }),
    ).toMatchObject({
      isVolumeDetailMode: true,
      isVolumeDetailConfigured: true,
      hasDelta: true,
      requestedTargetChapterCount: undefined,
      requestedTargetCharacterCount: undefined,
    })
  })

  it('对缺少上下文的请求返回明确错误', () => {
    expect(
      getStoryExpansionValidationError({
        expansionMode: 'total',
        currentChapterCount: 10,
        currentCharacterCount: 3,
        targetChapterCount: 18,
        hasStoryContext: false,
      }),
    ).toBe('请先准备好世界观和情节大纲，再执行协同扩展')
  })

  it('对单卷细化的无效章节范围返回校验错误', () => {
    expect(
      getStoryExpansionValidationError({
        expansionMode: 'volume_detail',
        currentChapterCount: 50,
        currentCharacterCount: 8,
        hasStoryContext: true,
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 5,
          },
        },
        targetVolumeIndex: 2,
        volumeChaptersMin: 20,
        volumeChaptersMax: 101,
      }),
    ).toBe('请输入有效的本卷细化章节范围（20-100）')
  })

  it('允许单卷细化将本卷上限设置到 100 章', () => {
    expect(
      getStoryExpansionValidationError({
        expansionMode: 'volume_detail',
        currentChapterCount: 50,
        currentCharacterCount: 8,
        hasStoryContext: true,
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 5,
          },
        },
        targetVolumeIndex: 2,
        volumeChaptersMin: 20,
        volumeChaptersMax: 100,
      }),
    ).toBeNull()
  })

  it('对常规协同超出单次上限的目标返回明确错误', () => {
    expect(
      getStoryExpansionValidationError({
        expansionMode: 'total',
        currentChapterCount: 20,
        currentCharacterCount: 8,
        targetChapterCount: 301,
        hasStoryContext: true,
      }),
    ).toBe('常规协同仅支持总规模不超过300个细化章节；超过300章后必须改用长篇框架协同')
  })

  it('当前章节数已经超过300章时禁止继续使用常规协同', () => {
    expect(
      getStoryExpansionValidationError({
        expansionMode: 'total',
        currentChapterCount: 320,
        currentCharacterCount: 12,
        targetCharacterCount: 15,
        hasStoryContext: true,
      }),
    ).toBe('常规协同仅支持总规模不超过300个细化章节；超过300章后必须改用长篇框架协同')
  })

  it('能识别目标卷是否会覆盖已有卷细纲', () => {
    expect(
      shouldConfirmStoryExpansionVolumeOverwrite(
        {
          has_framework: true,
          metadata: {
            expanded_volumes: [1, 3, 5],
          },
        },
        3,
      ),
    ).toBe(true)

    expect(
      shouldConfirmStoryExpansionVolumeOverwrite(
        {
          has_framework: true,
          metadata: {
            expanded_volumes: [1, 3, 5],
          },
        },
        4,
      ),
    ).toBe(false)
  })
})
