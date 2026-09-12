import type { TFunction } from 'i18next'

import type {
  StoryExpansionFrameworkMetadata,
  StoryExpansionMode,
} from '@/types/storyExpansion'
import {
  buildConventionalCollaborationLimitMessage,
  CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS,
  EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS,
  EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS,
  VOLUME_DETAIL_MAX_CHAPTERS,
  VOLUME_DETAIL_MIN_CHAPTERS,
} from './storyExpansionPolicy'

export interface StoryExpansionPlanningInput {
  expansionMode: StoryExpansionMode
  currentChapterCount: number
  currentCharacterCount: number
  targetChapterCount?: number | null
  targetCharacterCount?: number | null
  totalVolumes?: number | null
  totalChaptersMin?: number | null
  totalChaptersMax?: number | null
  frameworkMetadata?: StoryExpansionFrameworkMetadata | null
  targetVolumeIndex?: number | null
  volumeChaptersMin?: number | null
  volumeChaptersMax?: number | null
}

export interface StoryExpansionRequestPlan {
  isVolumeDetailMode: boolean
  isEpicFrameworkConfigured: boolean
  isVolumeDetailConfigured: boolean
  hasDelta: boolean
  requestedTargetChapterCount?: number
  requestedTargetCharacterCount?: number
  requestedChapterDelta: number
  requestedCharacterDelta: number
  requiresEpicFrameworkReset: boolean
}

export interface StoryExpansionValidationInput extends StoryExpansionPlanningInput {
  hasStoryContext: boolean
}

function isConfiguredNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isPositiveConfiguredNumber(value: number | null | undefined): value is number {
  return isConfiguredNumber(value) && value > 0
}

function getConventionalCollaborationMaxTargetChapterCount(): number {
  return CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
}

export function buildStoryExpansionRequestPlan(
  input: StoryExpansionPlanningInput,
): StoryExpansionRequestPlan {
  const isVolumeDetailMode = input.expansionMode === 'volume_detail'
  const requestedTargetChapterCount =
    input.expansionMode === 'epic_framework'
      ? (
        isConfiguredNumber(input.totalChaptersMax) && input.totalChaptersMax > input.currentChapterCount
          ? input.totalChaptersMax
          : undefined
      )
      : (
        isVolumeDetailMode
          ? undefined
          : (
            isConfiguredNumber(input.targetChapterCount) && input.targetChapterCount > input.currentChapterCount
              ? input.targetChapterCount
              : undefined
          )
      )
  const requestedTargetCharacterCount =
    input.expansionMode === 'epic_framework'
      ? undefined
      : (
        isConfiguredNumber(input.targetCharacterCount) && input.targetCharacterCount > input.currentCharacterCount
          ? input.targetCharacterCount
          : undefined
      )
  const requestedChapterDelta = Math.max(
    0,
    (requestedTargetChapterCount ?? input.currentChapterCount) - input.currentChapterCount,
  )
  const requestedCharacterDelta = Math.max(
    0,
    (requestedTargetCharacterCount ?? input.currentCharacterCount) - input.currentCharacterCount,
  )
  const isVolumeDetailConfigured = Boolean(
    input.frameworkMetadata?.has_framework
    && isPositiveConfiguredNumber(input.targetVolumeIndex)
    && isPositiveConfiguredNumber(input.volumeChaptersMin)
    && isPositiveConfiguredNumber(input.volumeChaptersMax)
    && input.volumeChaptersMin <= input.volumeChaptersMax,
  )
  const isEpicFrameworkConfigured = input.expansionMode === 'epic_framework'
    && isConfiguredNumber(input.totalVolumes)
    && input.totalVolumes >= 3
    && input.totalVolumes <= 50
    && isConfiguredNumber(input.totalChaptersMin)
    && isConfiguredNumber(input.totalChaptersMax)
    && input.totalChaptersMin >= EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS
    && input.totalChaptersMax <= EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS
    && input.totalChaptersMin <= input.totalChaptersMax
    && input.totalChaptersMax > input.currentChapterCount
  const hasDelta = isVolumeDetailMode
    ? isVolumeDetailConfigured
    : (
      input.expansionMode === 'epic_framework'
        ? isEpicFrameworkConfigured
        : (requestedChapterDelta > 0 || requestedCharacterDelta > 0)
    )

  return {
    isVolumeDetailMode,
    isEpicFrameworkConfigured,
    isVolumeDetailConfigured,
    hasDelta,
    requestedTargetChapterCount,
    requestedTargetCharacterCount,
    requestedChapterDelta,
    requestedCharacterDelta,
    requiresEpicFrameworkReset:
      input.expansionMode === 'total'
      && Boolean(input.frameworkMetadata?.has_framework)
      && requestedChapterDelta > 0,
  }
}

export function shouldConfirmStoryExpansionVolumeOverwrite(
  frameworkMetadata: StoryExpansionFrameworkMetadata | null | undefined,
  targetVolumeIndex: number | null | undefined,
): boolean {
  if (!isPositiveConfiguredNumber(targetVolumeIndex)) {
    return false
  }

  const expandedVolumes = Array.isArray(frameworkMetadata?.metadata?.expanded_volumes)
    ? frameworkMetadata.metadata.expanded_volumes
    : []

  return expandedVolumes.some((value) => Number(value) === targetVolumeIndex)
}

export function getStoryExpansionValidationError(
  input: StoryExpansionValidationInput,
  t?: TFunction,
): string | null {
  const plan = buildStoryExpansionRequestPlan(input)

  if (!input.hasStoryContext) {
    return t ? t('storyExpansion.planning.needStoryContext') : '请先准备好世界观和情节大纲，再执行协同扩展'
  }

  if (input.expansionMode === 'epic_framework') {
    if (!isConfiguredNumber(input.totalVolumes) || input.totalVolumes < 3 || input.totalVolumes > 50) {
      return t ? t('storyExpansion.planning.invalidEpicVolumes') : '长篇框架协同需要有效的总卷数（3-50）'
    }
    if (
      !isConfiguredNumber(input.totalChaptersMin)
      || !isConfiguredNumber(input.totalChaptersMax)
      || input.totalChaptersMin < EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS
      || input.totalChaptersMax > EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS
      || input.totalChaptersMin > input.totalChaptersMax
    ) {
      return t
        ? t('storyExpansion.planning.invalidEpicRange', {
          min: EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS,
          max: EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS,
        })
        : `长篇框架协同需要有效的总章节范围（${EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS}-${EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS}）`
    }
  }

  if (plan.isVolumeDetailMode) {
    if (!input.frameworkMetadata?.has_framework) {
      return t ? t('storyExpansion.planning.needEpicFrameworkFirst') : '单卷细化协同需要先生成长篇框架'
    }

    const totalVolumes = input.frameworkMetadata.metadata?.total_volumes || 50
    if (
      !isPositiveConfiguredNumber(input.targetVolumeIndex)
      || input.targetVolumeIndex > totalVolumes
    ) {
      return t
        ? t('storyExpansion.planning.invalidVolumeIndex', { max: totalVolumes })
        : `请输入有效的卷编号（1-${totalVolumes}）`
    }

    if (
      !isConfiguredNumber(input.volumeChaptersMin)
      || !isConfiguredNumber(input.volumeChaptersMax)
      || input.volumeChaptersMin < VOLUME_DETAIL_MIN_CHAPTERS
      || input.volumeChaptersMax > VOLUME_DETAIL_MAX_CHAPTERS
      || input.volumeChaptersMin > input.volumeChaptersMax
    ) {
      return t
        ? t('storyExpansion.planning.invalidVolumeRange', {
          min: VOLUME_DETAIL_MIN_CHAPTERS,
          max: VOLUME_DETAIL_MAX_CHAPTERS,
        })
        : `请输入有效的本卷细化章节范围（${VOLUME_DETAIL_MIN_CHAPTERS}-${VOLUME_DETAIL_MAX_CHAPTERS}）`
    }
  }

  if (!plan.isVolumeDetailMode && !plan.hasDelta) {
    return t ? t('storyExpansion.planning.needDeltaAboveCurrent') : '目标细化章节数或目标人物数至少要有一项高于当前值'
  }

  if (
    input.expansionMode === 'total'
    && Math.max(
      input.currentChapterCount,
      plan.requestedTargetChapterCount ?? input.currentChapterCount,
    ) > getConventionalCollaborationMaxTargetChapterCount()
  ) {
    return buildConventionalCollaborationLimitMessage(t)
  }

  if (
    input.expansionMode === 'epic_framework'
    && (plan.requestedTargetChapterCount ?? 0) > Math.max(EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS, input.currentChapterCount)
  ) {
    return t ? t('storyExpansion.planning.epicTargetExceeded') : '长篇框架协同当前目标超出章节规划上限，请缩小目标范围'
  }

  if ((plan.requestedTargetCharacterCount ?? 0) > Math.max(200, input.currentCharacterCount)) {
    return t ? t('storyExpansion.planning.characterTargetExceeded') : '协同扩展当前目标超出人物规划上限，请缩小目标范围'
  }

  return null
}

export function shouldSkipStoryExpansionAnalysisRequest(
  input: StoryExpansionValidationInput,
): boolean {
  if (!input.hasStoryContext) {
    return true
  }

  const plan = buildStoryExpansionRequestPlan(input)

  if (input.expansionMode === 'volume_detail') {
    if (!input.frameworkMetadata?.has_framework) {
      return true
    }
    if (!plan.isVolumeDetailConfigured) {
      return true
    }
  }

  if (input.expansionMode === 'epic_framework' && !plan.isEpicFrameworkConfigured) {
    return true
  }

  if (
    input.expansionMode === 'total'
    && Math.max(
      input.currentChapterCount,
      plan.requestedTargetChapterCount ?? input.currentChapterCount,
    ) > getConventionalCollaborationMaxTargetChapterCount()
  ) {
    return true
  }

  if (
    input.expansionMode === 'epic_framework'
    && (plan.requestedTargetChapterCount ?? 0) > Math.max(EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS, input.currentChapterCount)
  ) {
    return true
  }

  if ((plan.requestedTargetCharacterCount ?? 0) > Math.max(200, input.currentCharacterCount)) {
    return true
  }

  return false
}
