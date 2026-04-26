import { describe, expect, it } from 'vitest'

import { resolveStoryExpansionRecommendation } from '../storyExpansionRecommendation'

describe('storyExpansionRecommendation', () => {
  it('缺少项目信息时返回默认推荐', () => {
    expect(resolveStoryExpansionRecommendation(null)).toEqual({
      recommendedMode: 'total',
      recommendedVolumes: 3,
      recommendedChaptersPerVolumeMin: 20,
      recommendedChaptersPerVolumeMax: 30,
      recommendationReason: '',
    })
  })

  it('短篇项目推荐常规协同', () => {
    const recommendation = resolveStoryExpansionRecommendation({
      genre: '悬疑',
      planned_length_type: 'short',
      planned_chapters_max: 36,
    })

    expect(recommendation.recommendedMode).toBe('total')
    expect(recommendation.recommendationReason).toContain('短篇（36章）')
    expect(recommendation.recommendationReason).toContain('快速验证创意')
  })

  it('超长篇项目推荐长篇框架协同并统一章节范围文案', () => {
    const recommendation = resolveStoryExpansionRecommendation({
      genre: '玄幻',
      planned_length_type: 'epic',
      planned_chapters_max: 620,
    })

    expect(recommendation).toMatchObject({
      recommendedMode: 'epic_framework',
      recommendedVolumes: 12,
      recommendedChaptersPerVolumeMin: 45,
      recommendedChaptersPerVolumeMax: 70,
    })
    expect(recommendation.recommendationReason).toContain('单卷细化默认预填：60-80章')
    expect(recommendation.recommendationReason).toContain('先生成总纲、阶段路线图和分卷框架，再按卷滚动细化')
  })

  it('长篇修仙题材按题材配置推荐卷数和章节范围', () => {
    const recommendation = resolveStoryExpansionRecommendation({
      genre: '修仙',
      planned_length_type: 'long',
      planned_chapters_max: 320,
    })

    expect(recommendation).toMatchObject({
      recommendedMode: 'epic_framework',
      recommendedVolumes: 7,
      recommendedChaptersPerVolumeMin: 40,
      recommendedChaptersPerVolumeMax: 60,
    })
    expect(recommendation.recommendationReason).toContain('题材：修仙（境界体系）')
    expect(recommendation.recommendationReason).toContain('单卷细化默认预填：60-80章')
    expect(recommendation.recommendationReason).toContain('适用：先锁定境界大阶段，再按卷滚动细化每个故事台阶')
    expect(recommendation.recommendationReason).toContain('先生成总纲、阶段路线图和分卷框架，再按卷滚动细化')
  })

  it('中篇项目推荐渐进式扩展', () => {
    const recommendation = resolveStoryExpansionRecommendation({
      genre: '通用',
      planned_length_type: 'medium',
      planned_chapters_max: 72,
    })

    expect(recommendation.recommendedMode).toBe('total')
    expect(recommendation.recommendationReason).toContain('渐进式扩展')
    expect(recommendation.recommendationReason).toContain('中篇（72章）')
    expect(recommendation.recommendationReason).toContain('每轮新增20-60个细化章节左右')
  })

  it('未显式标记长篇时，450章以内项目仍优先常规协同', () => {
    const recommendation = resolveStoryExpansionRecommendation({
      genre: '玄幻',
      planned_length_type: '',
      planned_chapters_max: 420,
    })

    expect(recommendation.recommendedMode).toBe('total')
    expect(recommendation.recommendationReason).toContain('中篇（420章）')
  })
})
