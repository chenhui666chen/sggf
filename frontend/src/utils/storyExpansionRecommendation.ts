import type { Project } from '@/types/project'
import {
  CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS,
  EPIC_RECOMMENDATION_CHAPTER_THRESHOLD,
} from './storyExpansionPolicy'

export type StoryExpansionRecommendedMode = 'total' | 'epic_framework'

export interface StoryExpansionRecommendation {
  recommendedMode: StoryExpansionRecommendedMode
  recommendedVolumes: number
  recommendedChaptersPerVolumeMin: number
  recommendedChaptersPerVolumeMax: number
  recommendationReason: string
}

type StoryExpansionRecommendationProject = Pick<
  Project,
  'genre' | 'planned_length_type' | 'planned_chapters_max'
>

const DEFAULT_STORY_EXPANSION_RECOMMENDATION: StoryExpansionRecommendation = {
  recommendedMode: 'total',
  recommendedVolumes: 3,
  recommendedChaptersPerVolumeMin: 20,
  recommendedChaptersPerVolumeMax: 30,
  recommendationReason: '',
}
function clampRecommendationVolumeCount(
  value: number,
  maxVolumes: number,
  minVolumes = 3,
): number {
  return Math.max(minVolumes, Math.min(maxVolumes, value))
}

function buildRecommendationReason(lines: string[]): string {
  return lines.join('\n')
}

function resolveLongStoryGenreConfig(projectGenre: string, maxChapters: number): {
  estimatedVolumes: number
  chaptersPerVolumeMin: number
  chaptersPerVolumeMax: number
  genreLabel: string
  scenarioLabel: string
  usageHint: string
} {
  if (projectGenre === '修仙' || projectGenre === '玄幻') {
    return {
      estimatedVolumes: clampRecommendationVolumeCount(Math.ceil(maxChapters / 50), 18, 4),
      chaptersPerVolumeMin: 40,
      chaptersPerVolumeMax: 60,
      genreLabel: `${projectGenre}（境界体系）`,
      scenarioLabel: '长篇',
      usageHint: '适用：先锁定境界大阶段，再按卷滚动细化每个故事台阶',
    }
  }

  if (projectGenre === '都市') {
    return {
      estimatedVolumes: clampRecommendationVolumeCount(Math.ceil(maxChapters / 35), 14, 4),
      chaptersPerVolumeMin: 25,
      chaptersPerVolumeMax: 45,
      genreLabel: '都市（事业发展）',
      scenarioLabel: '长篇',
      usageHint: '适用：事业线、关系线、资源线交替推进',
    }
  }

  if (projectGenre === '悬疑') {
    return {
      estimatedVolumes: clampRecommendationVolumeCount(Math.ceil(maxChapters / 28), 12, 4),
      chaptersPerVolumeMin: 20,
      chaptersPerVolumeMax: 35,
      genreLabel: '悬疑（线索布局）',
      scenarioLabel: '长篇',
      usageHint: '适用：每卷完成一轮线索推进与阶段性反转',
    }
  }

  if (projectGenre === '言情' || projectGenre === '耽美') {
    return {
      estimatedVolumes: clampRecommendationVolumeCount(Math.ceil(maxChapters / 30), 12, 4),
      chaptersPerVolumeMin: 20,
      chaptersPerVolumeMax: 40,
      genreLabel: `${projectGenre}（感情递进）`,
      scenarioLabel: '长篇',
      usageHint: '适用：关系推进、情感反转与阶段性抉择并行',
    }
  }

  if (projectGenre === '科幻') {
    return {
      estimatedVolumes: clampRecommendationVolumeCount(Math.ceil(maxChapters / 45), 14, 4),
      chaptersPerVolumeMin: 30,
      chaptersPerVolumeMax: 55,
      genreLabel: '科幻（探索升级）',
      scenarioLabel: '长篇',
      usageHint: '适用：世界规则、探索层级与科技突破同步升级',
    }
  }

  return {
    estimatedVolumes: clampRecommendationVolumeCount(Math.ceil(maxChapters / 35), 12, 4),
    chaptersPerVolumeMin: 25,
    chaptersPerVolumeMax: 45,
    genreLabel: projectGenre || '通用',
    scenarioLabel: '长篇',
    usageHint: '',
  }
}

export function resolveStoryExpansionRecommendation(
  projectInfo: StoryExpansionRecommendationProject | null | undefined,
): StoryExpansionRecommendation {
  if (!projectInfo) {
    return DEFAULT_STORY_EXPANSION_RECOMMENDATION
  }

  const projectGenre = projectInfo.genre?.trim() || ''
  const lengthType = projectInfo.planned_length_type?.trim() || ''
  const maxChapters = Math.max(0, Number(projectInfo.planned_chapters_max || 0))

  if (lengthType === 'short' || maxChapters < 50) {
    return {
      ...DEFAULT_STORY_EXPANSION_RECOMMENDATION,
      recommendedMode: 'total',
      recommendationReason: buildRecommendationReason([
        '推荐「按总章数扩展」：',
        '',
        `• 题材：${projectGenre || '通用'}`,
        `• 篇幅：短篇（${maxChapters}章）`,
        '• 优势：快速规划，2分钟内完成',
        '• 适用：快速验证创意，无需复杂配置',
      ]),
    }
  }

  if (lengthType === 'epic' || maxChapters >= EPIC_RECOMMENDATION_CHAPTER_THRESHOLD) {
    const estimatedVolumes = clampRecommendationVolumeCount(Math.ceil(maxChapters / 55), 50, 8)
    return {
      recommendedMode: 'epic_framework',
      recommendedVolumes: estimatedVolumes,
      recommendedChaptersPerVolumeMin: 45,
      recommendedChaptersPerVolumeMax: 70,
      recommendationReason: buildRecommendationReason([
        '推荐「史诗框架」：',
        '',
        `• 题材：${projectGenre || '通用'}`,
        `• 篇幅：超长篇（${maxChapters}章）`,
        `• 推荐卷数：${estimatedVolumes}卷`,
        '• 单卷细化默认预填：60-80章',
        '• 扩展方式：先生成总纲、阶段路线图和分卷框架，再按卷滚动细化',
      ]),
    }
  }

  if (lengthType === 'long' || maxChapters > CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS) {
    const {
      estimatedVolumes,
      chaptersPerVolumeMin,
      chaptersPerVolumeMax,
      genreLabel,
      scenarioLabel,
      usageHint,
    } = resolveLongStoryGenreConfig(projectGenre, maxChapters)
    const reasonLines = [
      '推荐「史诗框架」：',
      '',
      `• 题材：${genreLabel}`,
      `• 篇幅：${scenarioLabel}（${maxChapters}章）`,
      `• 推荐卷数：${estimatedVolumes}卷`,
      '• 单卷细化默认预填：60-80章',
      '• 扩展方式：先生成总纲、阶段路线图和分卷框架，再按卷滚动细化',
    ]

    if (usageHint) {
      reasonLines.push(`• ${usageHint}`)
    }

    return {
      recommendedMode: 'epic_framework',
      recommendedVolumes: estimatedVolumes,
      recommendedChaptersPerVolumeMin: chaptersPerVolumeMin,
      recommendedChaptersPerVolumeMax: chaptersPerVolumeMax,
      recommendationReason: buildRecommendationReason(reasonLines),
    }
  }

  return {
    ...DEFAULT_STORY_EXPANSION_RECOMMENDATION,
    recommendedMode: 'total',
    recommendationReason: buildRecommendationReason([
      '推荐「渐进式扩展」：',
      '',
      `• 题材：${projectGenre || '通用'}`,
      `• 篇幅：中篇（${maxChapters}章）`,
      '• 优势：精细控制，随时调整',
      '• 适用：探索性写作，多线并进',
      '• 建议步长：每轮新增20-60个细化章节左右，质量与效率更均衡',
    ]),
  }
}
