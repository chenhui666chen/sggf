import type {
  StoryExpansionAnalysis,
  StoryExpansionFrameworkMetadata,
  StoryExpansionMode,
} from '@/types/storyExpansion'
import { buildStoryExpansionRequestPlan } from './storyExpansionPlanning'
import {
  buildConventionalCollaborationLimitMessage,
  buildConventionalCollaborationRecommendationMessage,
  CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS,
  CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS,
  EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS,
  EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS,
  FRAMEWORK_PREFERRED_TOTAL_FROM,
  VOLUME_DETAIL_MAX_CHAPTERS,
} from './storyExpansionPolicy'
import { formatStoryExpansionDurationRange } from './storyExpansionTiming'
import {
  getStoryExpansionExecutionModeLabel,
  STORY_EXPANSION_INTENT_LABELS,
  STORY_EXPANSION_MODE_LABELS,
  STORY_EXPANSION_STRATEGY_LABELS,
  STORY_PRESERVE_WRITTEN_MODE_LABELS,
} from './storyExpansionLabels'

export type StoryExpansionDialogChipColor =
  | 'default'
  | 'primary'
  | 'secondary'
  | 'success'
  | 'warning'
  | 'info'
  | 'error'

export interface StoryExpansionDialogChipView {
  key: string
  label: string
  color: StoryExpansionDialogChipColor
}

export interface StoryExpansionDialogBandView {
  key: string
  label: string
  rangeText: string
  detail: string
}

export interface StoryExpansionDialogModeSuitabilityView {
  chips: StoryExpansionDialogChipView[]
  summary: string
  reason: string
  bands: StoryExpansionDialogBandView[]
}

export type StoryExpansionDialogFieldKey =
  | 'targetChapterCount'
  | 'targetCharacterCount'
  | 'totalVolumes'
  | 'totalChaptersMin'
  | 'totalChaptersMax'
  | 'targetVolumeIndex'
  | 'volumeChaptersMin'
  | 'volumeChaptersMax'
  | 'displayedTargetCharacterCount'
  | 'volumeCharacterIncrement'

export interface StoryExpansionDialogFieldView {
  key: StoryExpansionDialogFieldKey
  label: string
  helperText: string
  placeholder?: string
  readOnly?: boolean
  min?: number
  max?: number
  fullWidth?: boolean
  flex?: string
}

export interface StoryExpansionDialogConfigAlertView {
  key: string
  severity: 'info' | 'warning'
  variant?: 'standard' | 'outlined'
  text: string
}

const VOLUME_DETAIL_INPUT_MAX_CHAPTERS = VOLUME_DETAIL_MAX_CHAPTERS

export type StoryExpansionDialogConfigBlock =
  | {
    kind: 'alert'
    key: string
    alert: StoryExpansionDialogConfigAlertView
  }
  | {
    kind: 'fields'
    key: string
    fields: StoryExpansionDialogFieldView[]
  }

export interface StoryExpansionDialogViewInput {
  currentChapterCount: number
  currentCharacterCount: number
  recommendedMode?: StoryExpansionMode | null
  targetChapterCount: number | null
  targetCharacterCount: number | null
  expansionMode: StoryExpansionMode
  totalVolumes: number | null
  totalChaptersMin: number | null
  totalChaptersMax: number | null
  frameworkMetadata?: StoryExpansionFrameworkMetadata | null
  targetVolumeIndex: number | null
  volumeChaptersMin: number | null
  volumeChaptersMax: number | null
  volumeCharacterIncrement: number | null
  analysis: StoryExpansionAnalysis | null
}

export interface StoryExpansionDialogViewModel {
  isVolumeDetailMode: boolean
  isLockedToVolumeDetail: boolean
  currentChapterChipLabel: string
  currentCharacterChipLabel: string
  currentCountHelperText: string
  displayedTargetCharacterCount: number | null
  chapterDeltaLabel: string
  chapterDeltaChipLabel: string
  characterDeltaLabel: string
  characterDeltaChipLabel: string
  hasDelta: boolean
  analysisWarnings: string[]
  autoEstimateHints: string[]
  hasAnalysis: boolean
  precheckChips: StoryExpansionDialogChipView[]
  analysisSummaryText: string
  modeSuitabilityView: StoryExpansionDialogModeSuitabilityView | null
  intentReasonText: string
  executionModeReasonText: string
  writtenContextText: string
  autoSupplementText: string
  epicConfigText: string
  volumeDetailText: string
  volumeCharacterPlanText: string
  modelPlanLines: string[]
  validationMessage: string
  expansionModeHelperText: string
  lockedModeAlertText: string
  writtenModeInfoAlertText: string
  autoSupplementLabel: string
  configBlocks: StoryExpansionDialogConfigBlock[]
}

function isConfiguredNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function getSuitabilityChipColor(band?: string): StoryExpansionDialogChipColor {
  if (band === 'recommended') {
    return 'success'
  }
  if (band === 'forbidden') {
    return 'error'
  }
  if (band === 'caution') {
    return 'warning'
  }
  if (band === 'framework_preferred') {
    return 'info'
  }
  if (band === 'epic') {
    return 'error'
  }
  return 'default'
}

function filterModeSuitabilityBands(
  requestBand: string | undefined,
  bands: Array<{ key?: string, label?: string, range_text?: string, detail?: string }> | undefined,
): Array<{ key?: string, label?: string, range_text?: string, detail?: string }> {
  if (!Array.isArray(bands)) {
    return []
  }

  const preferredKeys = (
    requestBand === 'recommended'
      ? ['recommended', 'caution', 'forbidden']
      : (
        requestBand === 'caution'
          ? ['caution', 'forbidden']
          : (
            requestBand === 'forbidden'
              ? ['forbidden']
              : (
                requestBand === 'framework_preferred'
                  ? ['framework_preferred', 'epic']
                  : (requestBand === 'epic' ? ['epic'] : [])
              )
          )
      )
  )

  if (!preferredKeys.length) {
    return bands
  }

  const filtered = bands.filter((item) => preferredKeys.includes(trimText(item.key)))
  return filtered.length ? filtered : bands
}

function trimText(value: string | null | undefined): string {
  return typeof value === 'string' ? value.trim() : ''
}

function toSafePositiveInt(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

function formatPositiveIntRange(minValue: number | null, maxValue: number | null): string {
  if (minValue == null && maxValue == null) {
    return ''
  }

  const start = minValue ?? maxValue
  const end = maxValue ?? minValue
  if (start == null || end == null) {
    return ''
  }
  if (start >= end) {
    return `${start}`
  }
  return `${start}-${end}`
}

function toDetailedChapterCountLabel(value: number): string {
  return `${value}个细化章节`
}

function getConventionalCollaborationMaxTargetChapterCount(): number {
  return CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
}

function normalizeDetailedChapterRangeText(rangeText?: string | null): string {
  const value = trimText(rangeText)
  if (!value) {
    return ''
  }

  const explicitRangeMatch = value.match(/^(\d+)\s*-\s*(\d+)\s*章$/)
  if (explicitRangeMatch) {
    return `${explicitRangeMatch[1]}-${explicitRangeMatch[2]}个细化章节`
  }

  const singleValueMatch = value.match(/^(\d+)\s*章$/)
  if (singleValueMatch) {
    return toDetailedChapterCountLabel(Number.parseInt(singleValueMatch[1], 10))
  }

  return value
}

function buildCompactAnalysisSummary(summaryText: string): string {
  const value = trimText(summaryText)
  if (!value) {
    return ''
  }

  const segments = value
    .split(/[；;]/)
    .map((item) => item.trim())
    .filter(Boolean)

  if (segments.length <= 3) {
    return segments.join('；')
  }
  return segments.slice(0, 3).join('；')
}

function createField(
  key: StoryExpansionDialogFieldKey,
  label: string,
  helperText: string,
  options: Partial<Omit<StoryExpansionDialogFieldView, 'key' | 'label' | 'helperText'>> = {},
): StoryExpansionDialogFieldView {
  return {
    key,
    label,
    helperText,
    ...options,
  }
}

function buildEpicFrameworkCharacterPolicyText(input: {
  recommendedRangeText: string
  stageTargetCharacterCount: number | null
  effectiveAnalysisTargetCharacterCount: number | null
  followUpPhaseText: string
}): string {
  const parts: string[] = []

  if (input.recommendedRangeText) {
    parts.push(`全书建议规模约 ${input.recommendedRangeText} 人`)
  }

  if (input.stageTargetCharacterCount != null) {
    parts.push(`框架阶段先补到 ${input.stageTargetCharacterCount} 人`)
  } else if (input.effectiveAnalysisTargetCharacterCount != null) {
    parts.push(`框架阶段预计补到 ${input.effectiveAnalysisTargetCharacterCount} 人`)
  }

  if (input.followUpPhaseText) {
    parts.push(`其余人物会在${input.followUpPhaseText}继续补齐`)
  }

  if (!parts.length) {
    return '长篇框架阶段只建立核心人物骨架，不在此处直接手填全书目标人物数；卷内功能角色与细分人物会在后续单卷细化中逐步补齐。'
  }

  return `${parts.join('；')}。`
}

export function createStoryExpansionDialogView(
  input: StoryExpansionDialogViewInput,
): StoryExpansionDialogViewModel {
  const analysis = input.analysis
  const autoCharacterPlan = analysis?.auto_supplement?.character_plan
  const isEpicFrameworkMode = input.expansionMode === 'epic_framework'
  const isVolumeDetailMode = input.expansionMode === 'volume_detail'
  const hasFramework = !!input.frameworkMetadata?.has_framework
  const isEpicFrameworkRecommended = input.recommendedMode === 'epic_framework'
  const isLockedToVolumeDetail = false
  const effectiveAnalysisTargetChapterCount = (
    typeof analysis?.effective_target_chapter_count === 'number'
    && analysis.effective_target_chapter_count > input.currentChapterCount
  )
    ? analysis.effective_target_chapter_count
    : null
  const effectiveAnalysisTargetCharacterCount = (
    typeof analysis?.effective_target_character_count === 'number'
    && analysis.effective_target_character_count > input.currentCharacterCount
  )
    ? analysis.effective_target_character_count
    : null
  const effectiveAnalysisVolumeCharacterIncrement = typeof analysis?.volume_detail?.character_increment === 'number'
    ? Math.max(0, analysis.volume_detail.character_increment)
    : null
  const recommendedCharacterAdditionalMin = toSafePositiveInt(autoCharacterPlan?.recommended_additional_min)
  const recommendedCharacterAdditionalMax = toSafePositiveInt(autoCharacterPlan?.recommended_additional_max)
  const recommendedCharacterAdditionalRangeText = formatPositiveIntRange(
    recommendedCharacterAdditionalMin,
    recommendedCharacterAdditionalMax,
  )
  const recommendedCharacterRangeText = trimText(autoCharacterPlan?.recommended_range_text)
  const stageTargetCharacterCount = toSafePositiveInt(autoCharacterPlan?.stage_target_characters)
  const taskTargetCharacterCount = toSafePositiveInt(autoCharacterPlan?.task_target_characters)
  const taskTargetCharacterIncrement = toSafePositiveInt(autoCharacterPlan?.task_target_increment)
  const followUpPhaseText = trimText(autoCharacterPlan?.follow_up_phase)

  const requestPlan = buildStoryExpansionRequestPlan({
    expansionMode: input.expansionMode,
    currentChapterCount: input.currentChapterCount,
    currentCharacterCount: input.currentCharacterCount,
    targetChapterCount: input.targetChapterCount,
    targetCharacterCount: input.targetCharacterCount,
    totalVolumes: input.totalVolumes,
    totalChaptersMin: input.totalChaptersMin,
    totalChaptersMax: input.totalChaptersMax,
    frameworkMetadata: input.frameworkMetadata,
    targetVolumeIndex: input.targetVolumeIndex,
    volumeChaptersMin: input.volumeChaptersMin,
    volumeChaptersMax: input.volumeChaptersMax,
  })

  const effectiveTargetChapterCount = isEpicFrameworkMode
    ? input.totalChaptersMax
    : input.targetChapterCount
  const displayedTargetChapterCount = effectiveTargetChapterCount ?? effectiveAnalysisTargetChapterCount
  const targetChapterCountForWarnings = displayedTargetChapterCount ?? input.currentChapterCount
  const chapterDelta = isVolumeDetailMode
    ? Math.max(0, input.volumeChaptersMax ?? 0)
    : Math.max(0, (displayedTargetChapterCount ?? input.currentChapterCount) - input.currentChapterCount)
  const chapterDeltaLabel = isVolumeDetailMode
    ? (
      isConfiguredNumber(input.volumeChaptersMin) && isConfiguredNumber(input.volumeChaptersMax)
        ? `${input.volumeChaptersMin}-${input.volumeChaptersMax}`
        : '待设定'
    )
    : (
      isEpicFrameworkMode
        ? (
          isConfiguredNumber(input.totalChaptersMin) && isConfiguredNumber(input.totalChaptersMax)
            ? `${input.totalChaptersMin}-${input.totalChaptersMax}`
            : (
              effectiveAnalysisTargetChapterCount != null
                ? `${effectiveAnalysisTargetChapterCount}`
                : '待设定'
            )
        )
        : (
          effectiveTargetChapterCount == null && effectiveAnalysisTargetChapterCount != null
            ? `系统估算 ${chapterDelta}`
            : `${chapterDelta}`
        )
    )
  const chapterDeltaChipLabel = isVolumeDetailMode
    ? '本卷细化章节'
    : (isEpicFrameworkMode ? '规划总章' : '本轮新增细化章节')

  const displayedTargetCharacterCount = isVolumeDetailMode
    ? (analysis?.volume_detail?.target_character_count ?? input.targetCharacterCount ?? input.currentCharacterCount)
    : (
      isEpicFrameworkMode
        ? effectiveAnalysisTargetCharacterCount
        : (input.targetCharacterCount ?? effectiveAnalysisTargetCharacterCount)
    )
  const characterDelta = isVolumeDetailMode
    ? Math.max(0, input.volumeCharacterIncrement ?? effectiveAnalysisVolumeCharacterIncrement ?? 0)
    : Math.max(0, (displayedTargetCharacterCount ?? input.currentCharacterCount) - input.currentCharacterCount)
  const characterDeltaLabel = isVolumeDetailMode
    ? (
      input.volumeCharacterIncrement == null && effectiveAnalysisVolumeCharacterIncrement != null
        ? `系统估算 ${effectiveAnalysisVolumeCharacterIncrement}`
        : (
          input.volumeCharacterIncrement == null
            ? '自动估算'
            : `${characterDelta}`
        )
    )
    : (
      isEpicFrameworkMode
        ? (
          effectiveAnalysisTargetCharacterCount != null
            ? `系统估算 ${characterDelta}`
            : '自动估算'
        )
        : (
          input.targetCharacterCount == null && effectiveAnalysisTargetCharacterCount != null
            ? `系统估算 ${characterDelta}`
            : `${characterDelta}`
        )
    )
  const characterDeltaChipLabel = isVolumeDetailMode
    ? '计划补足人物'
    : (isEpicFrameworkMode ? '计划补足人物' : '本轮新增人物')

  const autoEstimateHints: string[] = []
  if (!isVolumeDetailMode && input.targetChapterCount == null && effectiveAnalysisTargetChapterCount != null) {
    autoEstimateHints.push(`目标细化章节数留空时，系统预估为 ${toDetailedChapterCountLabel(effectiveAnalysisTargetChapterCount)}`)
  }
  if (isVolumeDetailMode) {
    if (input.volumeCharacterIncrement == null && effectiveAnalysisVolumeCharacterIncrement != null) {
      autoEstimateHints.push(`本卷新增人物上限留空时，系统预估为 ${effectiveAnalysisVolumeCharacterIncrement} 人`)
    }
  } else if (input.targetCharacterCount == null && effectiveAnalysisTargetCharacterCount != null) {
    const stageLabel = trimText(autoCharacterPlan?.stage_label) || ((analysis?.auto_supplement?.character_delta || 0) > 0 ? '首轮' : '')
    const recommendedRangeText = recommendedCharacterRangeText
    const followUpPhase = followUpPhaseText
    if (recommendedCharacterAdditionalRangeText) {
      autoEstimateHints.push(`建议补充人物：约 ${recommendedCharacterAdditionalRangeText} 人`)
    }
    if (
      taskTargetCharacterCount != null
      && stageTargetCharacterCount != null
      && taskTargetCharacterCount > stageTargetCharacterCount
    ) {
      autoEstimateHints.push(
        `点击一次开始后，系统会自动分轮推进；首轮先补到 ${effectiveAnalysisTargetCharacterCount} 人，不是只补 ${(analysis?.auto_supplement?.character_delta || 0)} 人就结束。`,
      )
    }
    autoEstimateHints.push(
      (analysis?.auto_supplement?.character_delta || 0) > 0
        ? `目标人物数留空时，系统${stageLabel || '本轮'}先补到 ${effectiveAnalysisTargetCharacterCount} 人`
        : `目标人物数留空时，系统预估为 ${effectiveAnalysisTargetCharacterCount} 人`,
    )
    if (
      taskTargetCharacterCount != null
      && stageTargetCharacterCount != null
      && taskTargetCharacterCount > stageTargetCharacterCount
    ) {
      autoEstimateHints.push(
        taskTargetCharacterIncrement != null
          ? `本次自动协同预计补到 ${taskTargetCharacterCount} 人（约新增 ${taskTargetCharacterIncrement} 人）`
          : `本次自动协同预计补到 ${taskTargetCharacterCount} 人`,
      )
    }
    if (recommendedRangeText) {
      autoEstimateHints.push(
        followUpPhase
          ? `全书结构化人物建议规模约为 ${recommendedRangeText} 人；剩余角色会在${followUpPhase}继续补齐`
          : `全书结构化人物建议规模约为 ${recommendedRangeText} 人`,
      )
    }
  }

  const effectiveIntent = trimText(analysis?.effective_intent) || trimText(analysis?.recommended_intent)
  const effectiveStrategy = trimText(analysis?.effective_strategy) || trimText(analysis?.recommended_strategy)
  const effectiveExpansionMode = trimText(analysis?.effective_expansion_mode)
  const estimatedRounds = analysis?.estimated_rounds ?? analysis?.model_plan?.estimated_rounds ?? 1
  const estimatedDurationText = formatStoryExpansionDurationRange(
    analysis?.estimated_duration_minutes_min ?? null,
    analysis?.estimated_duration_minutes_max ?? null,
  )
  const precheckChips: StoryExpansionDialogChipView[] = analysis
    ? [
      {
        key: 'intent',
        label: `系统主导 ${STORY_EXPANSION_INTENT_LABELS[effectiveIntent] || effectiveIntent || '未提供'}`,
        color: 'primary',
      },
      {
        key: 'strategy',
        label: `执行顺序 ${STORY_EXPANSION_STRATEGY_LABELS[effectiveStrategy] || effectiveStrategy || '未提供'}`,
        color: 'success',
      },
      {
        key: 'execution-mode',
        label: `执行模式 ${getStoryExpansionExecutionModeLabel(analysis.execution_mode, '未提供')}`,
        color: 'secondary',
      },
      {
        key: 'expansion-mode',
        label: `扩展形态 ${STORY_EXPANSION_MODE_LABELS[effectiveExpansionMode] || effectiveExpansionMode || '常规协同'}`,
        color: 'info',
      },
      ...(recommendedCharacterAdditionalRangeText
        ? [{
          key: 'character-suggestion',
          label: `建议补人 ${recommendedCharacterAdditionalRangeText} 人`,
          color: 'warning' as const,
        }]
        : []),
      ...(taskTargetCharacterCount != null && taskTargetCharacterCount > input.currentCharacterCount
        ? [{
          key: 'character-task-target',
          label: `本次预计补到 ${taskTargetCharacterCount} 人`,
          color: 'secondary' as const,
        }, {
          key: 'character-auto-rounds',
          label: '点击一次后自动分轮',
          color: 'info' as const,
        }]
        : []),
      {
        key: 'estimated-rounds',
        label: `预计轮次 ${estimatedRounds}`,
        color: 'default',
      },
      {
        key: 'score',
        label: `协同评分 ${analysis.validation?.score ?? 0}`,
        color: 'warning',
      },
    ]
    : []
  if (estimatedDurationText && precheckChips.length > 0) {
    precheckChips.splice(Math.max(0, precheckChips.length - 1), 0, {
      key: 'estimated-duration',
      label: `预计耗时 ${estimatedDurationText}`,
      color: 'default',
    })
  }

  const modeSuitabilityView = analysis?.mode_suitability?.mode === 'total'
    ? {
      chips: [
        {
          key: 'request-band',
          label: `适用结论 ${analysis.mode_suitability.request_band_label || '未评估'}`,
          color: getSuitabilityChipColor(analysis.mode_suitability.request_band),
        },
        ...(analysis.mode_suitability.preferred_iterative_step
          ? [{
            key: 'preferred-step',
            label: `建议步长 ${toDetailedChapterCountLabel(analysis.mode_suitability.preferred_iterative_step)}`,
            color: 'default' as const,
          }]
          : []),
        ...(analysis.mode_suitability.single_round_delta_limit
          ? [{
            key: 'single-round-limit',
            label: `单轮上限 ${toDetailedChapterCountLabel(analysis.mode_suitability.single_round_delta_limit)}`,
            color: 'default' as const,
          }]
          : []),
      ],
      summary: trimText(analysis.mode_suitability.summary),
      reason: trimText(analysis.mode_suitability.request_band_reason),
      bands: filterModeSuitabilityBands(
        analysis.mode_suitability.request_band,
        analysis.mode_suitability.bands,
      ).map((item, index) => ({
          key: `${item.key || item.label || 'band'}-${index}`,
          label: trimText(item.label) || '区间',
          rangeText: normalizeDetailedChapterRangeText(item.range_text),
          detail: trimText(item.detail),
        })),
    }
    : null

  const writtenContextText = analysis?.written_chapter_context?.applied
    ? (
      `已检测到 ${analysis.written_chapter_context.written_chapter_count || 0} 章正文，当前按“${
        STORY_PRESERVE_WRITTEN_MODE_LABELS[analysis.written_chapter_context.preserve_written_mode || '']
        || analysis.written_chapter_context.preserve_written_mode
        || '未知模式'
      }”参与协同。`
    )
    : ''

  const autoSupplementText = (
    (analysis?.auto_supplement?.chapter_delta || 0) > 0
    || (analysis?.auto_supplement?.character_delta || 0) > 0
  )
    ? [
      (
        taskTargetCharacterCount != null
        && stageTargetCharacterCount != null
        && taskTargetCharacterCount > stageTargetCharacterCount
      )
        ? `点击一次开始后，系统会自动连续执行多轮；首轮补足 ${(analysis?.auto_supplement?.character_delta || 0)} 个配套人物只是起点，不是整次任务上限。`
        : '',
      (analysis?.auto_supplement?.chapter_delta || 0) > 0
        ? `系统会自动补足 ${analysis?.auto_supplement?.chapter_delta} 个承接章节。`
        : '',
      (analysis?.auto_supplement?.character_delta || 0) > 0
        ? (
          taskTargetCharacterCount != null
          && stageTargetCharacterCount != null
          && taskTargetCharacterCount > stageTargetCharacterCount
            ? `首轮会自动补足 ${analysis?.auto_supplement?.character_delta} 个配套人物。`
            : `系统会自动补足 ${analysis?.auto_supplement?.character_delta} 个配套人物。`
        )
        : '',
      (() => {
        const recommendedRangeText = recommendedCharacterRangeText
        const stageLabel = trimText(autoCharacterPlan?.stage_label)
        const stageTarget = stageTargetCharacterCount
        const taskTarget = taskTargetCharacterCount
        const taskIncrement = taskTargetCharacterIncrement
        const remaining = toSafePositiveInt(autoCharacterPlan?.remaining_to_recommended_min)
        const followUpPhase = followUpPhaseText
        if (!recommendedRangeText || !stageLabel || stageTarget == null) {
          return ''
        }
        const taskTargetText = taskTarget != null && taskTarget > stageTarget
          ? (
            taskIncrement != null
              ? `本次自动协同预计补到 ${taskTarget} 人（约新增 ${taskIncrement} 人）。`
              : `本次自动协同预计补到 ${taskTarget} 人。`
          )
          : ''
        const remainingText = remaining != null && followUpPhase
          ? `距离建议下限还差约 ${remaining} 人，会在${followUpPhase}继续补齐。`
          : ''
        return `人物计划：全书建议规模约为 ${recommendedRangeText} 人，${stageLabel}先补到 ${stageTarget} 人。${taskTargetText}${remainingText}`.trim()
      })(),
    ].filter(Boolean).join(' ')
    : ''

  const epicConfigText = analysis?.epic_config?.chapter_range?.length
    ? `长篇框架规模：${analysis.epic_config.total_volumes || '未定'} 卷 / ${analysis.epic_config.chapter_range[0]}-${analysis.epic_config.chapter_range[1]} 章`
    : ''

  const volumeDetailText = analysis?.volume_detail?.chapter_range?.length
    ? `单卷细化目标：第${analysis.volume_detail.target_volume_index || '未定'}卷 / 第${analysis.volume_detail.chapter_range[0]}-${analysis.volume_detail.chapter_range[1]}章${analysis.volume_detail.existing_detail ? '（将覆盖原有细纲）' : ''}`
    : ''

  const volumeCharacterPlanText = typeof analysis?.volume_detail?.character_increment === 'number'
    ? `本卷人物计划：新增不超过 ${analysis.volume_detail.character_increment} 人，对齐后的全书人物目标为 ${analysis.volume_detail.target_character_count || input.currentCharacterCount} 人。`
    : ''

  const compactAnalysisSummaryText = buildCompactAnalysisSummary(analysis?.analysis_summary || '')
  const compactAutoEstimateHints = (() => {
    if (isVolumeDetailMode) {
      if (input.volumeCharacterIncrement == null && effectiveAnalysisVolumeCharacterIncrement != null) {
        return [`本卷人物留空时，系统预计新增 ${effectiveAnalysisVolumeCharacterIncrement} 人。`]
      }
      return []
    }

    if (isEpicFrameworkMode && effectiveAnalysisTargetCharacterCount != null) {
      return [buildEpicFrameworkCharacterPolicyText({
        recommendedRangeText: recommendedCharacterRangeText,
        stageTargetCharacterCount,
        effectiveAnalysisTargetCharacterCount,
        followUpPhaseText,
      })]
    }

    if (input.targetCharacterCount == null && effectiveAnalysisTargetCharacterCount != null) {
      const parts: string[] = []
      if (recommendedCharacterAdditionalRangeText) {
        parts.push(`建议补人约 ${recommendedCharacterAdditionalRangeText} 人`)
      }
      if (
        taskTargetCharacterCount != null
        && stageTargetCharacterCount != null
        && taskTargetCharacterCount > stageTargetCharacterCount
      ) {
        parts.push(`首轮先补到 ${effectiveAnalysisTargetCharacterCount} 人`)
        parts.push(`本次任务预计补到 ${taskTargetCharacterCount} 人`)
      } else {
        parts.push(`人物留空时系统预计补到 ${effectiveAnalysisTargetCharacterCount} 人`)
      }
      return parts.length > 0 ? [`${parts.join('；')}。`] : []
    }

    if (input.targetChapterCount == null && effectiveAnalysisTargetChapterCount != null) {
      const estimatedChapterDelta = Math.max(0, effectiveAnalysisTargetChapterCount - input.currentChapterCount)
      return [
        estimatedChapterDelta > 0
          ? `章节留空时，系统预计先补到 ${effectiveAnalysisTargetChapterCount} 章（较当前新增 ${estimatedChapterDelta} 章）。`
          : `章节留空时，系统预计补到 ${effectiveAnalysisTargetChapterCount} 章。`,
      ]
    }

    return []
  })()
  const compactModeSuitabilityView = analysis?.mode_suitability?.mode === 'total'
    ? {
      chips: modeSuitabilityView?.chips || [],
      summary: buildConventionalCollaborationRecommendationMessage(),
      reason: '',
      bands: [],
    }
    : modeSuitabilityView
  const compactAutoSupplementText = isVolumeDetailMode
    ? autoSupplementText
    : ''

  const configBlocks: StoryExpansionDialogConfigBlock[] = []
  if (input.expansionMode === 'epic_framework') {
    configBlocks.push({
      kind: 'alert',
      key: 'epic-framework-info',
      alert: {
        key: 'epic-framework-info',
        severity: 'info',
        text: '长篇框架协同会先规划故事总纲、阶段路线图、分卷框架和滚动细化策略，不会一次性直接铺满上千章细纲。',
      },
    })
    if (hasFramework) {
      configBlocks.push({
        kind: 'alert',
        key: 'epic-framework-regenerate-warning',
        alert: {
          key: 'epic-framework-regenerate-warning',
          severity: 'warning',
          variant: 'outlined',
          text: '当前项目已存在长篇框架。重新生成成功后会覆盖现有框架，并清空已展开卷的细纲，后续需要按新框架重新做单卷细化。',
        },
      })
    }
    configBlocks.push({
      kind: 'fields',
      key: 'epic-framework-fields',
      fields: [
        createField('totalVolumes', '总卷数', '建议 3-50 卷', {
          min: 3,
          max: 50,
          flex: '1 1 160px',
        }),
        createField('totalChaptersMin', '总章范围最小值', '建议 300-5000 章', {
          min: EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS,
          max: EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS,
          flex: '1 1 180px',
        }),
        createField('totalChaptersMax', '总章范围最大值', '会作为框架规模上限', {
          min: EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS,
          max: EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS,
          flex: '1 1 180px',
        }),
      ],
    })
    configBlocks.push({
      kind: 'alert',
      key: 'epic-framework-character-policy',
      alert: {
        key: 'epic-framework-character-policy',
        severity: 'info',
        variant: 'outlined',
        text: buildEpicFrameworkCharacterPolicyText({
          recommendedRangeText: recommendedCharacterRangeText,
          stageTargetCharacterCount,
          effectiveAnalysisTargetCharacterCount,
          followUpPhaseText,
        }),
      },
    })
  } else if (isVolumeDetailMode) {
    configBlocks.push({
      kind: 'alert',
      key: 'volume-framework-status',
      alert: {
        key: 'volume-framework-status',
        severity: hasFramework ? 'info' : 'warning',
        text: hasFramework
          ? `已检测到长篇框架，可直接细化单卷。当前框架共 ${input.frameworkMetadata?.metadata?.total_volumes || '未识别'} 卷，已展开卷：${input.frameworkMetadata?.metadata?.expanded_volumes?.length ? input.frameworkMetadata.metadata.expanded_volumes.join('、') : '暂无'}。`
          : '单卷细化协同需要先存在长篇框架。若当前项目还没有框架，请先使用"长篇框架协同"生成总卷框架。',
      },
    })
    configBlocks.push({
      kind: 'fields',
      key: 'volume-detail-fields',
      fields: [
        createField('targetVolumeIndex', '目标卷编号', `范围 1-${input.frameworkMetadata?.metadata?.total_volumes || 50}`, {
          min: 1,
          max: Math.max(1, input.frameworkMetadata?.metadata?.total_volumes || 50),
          flex: '1 1 160px',
        }),
        createField('volumeChaptersMin', '本卷最少章节', '建议 60-80 章', {
          min: 20,
          max: VOLUME_DETAIL_INPUT_MAX_CHAPTERS,
          flex: '1 1 180px',
        }),
        createField('volumeChaptersMax', '本卷最多章节', '建议尽量控制在 80 章内；必要时可放宽到 120 章', {
          min: 20,
          max: VOLUME_DETAIL_INPUT_MAX_CHAPTERS,
          flex: '1 1 180px',
        }),
      ],
    })
    configBlocks.push({
      kind: 'alert',
      key: 'volume-character-info',
      alert: {
        key: 'volume-character-info',
        severity: 'info',
        variant: 'outlined',
        text: '下方只读人物字段仅作全书角色规模参考；系统会优先补齐与当前卷剧情承接相关的人物。若本轮人物留空，请将“本卷新增人物上限”留空，由系统自动估算。',
      },
    })
    configBlocks.push({
      kind: 'fields',
      key: 'volume-character-fields',
      fields: [
        createField('displayedTargetCharacterCount', '全书目标人物数（只读）', '仅作全书角色规模参考，单卷细化模式下不直接编辑。', {
          readOnly: true,
          flex: '1 1 220px',
        }),
        createField(
          'volumeCharacterIncrement',
          '本卷新增人物上限',
          input.volumeCharacterIncrement == null
            ? '留空则由系统结合本卷剧情承接自动估算。'
            : '输入 0 表示本轮不新增人物，建议单轮 0-6。',
          {
            placeholder: '留空则由系统自动估算',
            min: 0,
            max: 30,
            flex: '1 1 220px',
          },
        ),
      ],
    })
  } else {
    if (isEpicFrameworkRecommended && input.expansionMode === 'total' && !hasFramework) {
      configBlocks.push({
        kind: 'alert',
        key: 'total-epic-recommendation-alert',
        alert: {
          key: 'total-epic-recommendation-alert',
          severity: 'warning',
          text: `当前项目按篇幅规划更适合“长篇框架协同”。若本轮只是补少量细化章节或人物，且总规模仍不超过${CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS}章，可以继续常规协同；若准备推进 ${FRAMEWORK_PREFERRED_TOTAL_FROM} 章及以上主线，请优先切换到长篇框架协同。`,
        },
      })
    }

    const isConventionalCollaborationCaution = (
      input.expansionMode === 'total'
      && Math.max(input.currentChapterCount, targetChapterCountForWarnings) > CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS
      && Math.max(input.currentChapterCount, targetChapterCountForWarnings) <= CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
    )
    const isConventionalCollaborationForbidden = (
      input.expansionMode === 'total'
      && Math.max(input.currentChapterCount, targetChapterCountForWarnings) > CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
    )

    if (isConventionalCollaborationCaution) {
      configBlocks.push({
        kind: 'alert',
        key: 'total-conventional-caution-alert',
        alert: {
          key: 'total-conventional-caution-alert',
          severity: 'warning',
          text: buildConventionalCollaborationRecommendationMessage(),
        },
      })
    }

    if (isConventionalCollaborationForbidden) {
      configBlocks.push({
        kind: 'alert',
        key: 'total-conventional-range-alert',
        alert: {
          key: 'total-conventional-range-alert',
          severity: 'warning',
          text: `当前总规模已超过常规协同上限 ${toDetailedChapterCountLabel(CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS)}。请改选“长篇框架协同”。`,
        },
      })
    }

    configBlocks.push({
      kind: 'fields',
      key: 'total-fields',
      fields: [
        createField(
          'targetChapterCount',
          '目标细化章节数',
          isConventionalCollaborationForbidden
            ? buildConventionalCollaborationLimitMessage()
            : (
              isConventionalCollaborationCaution
                ? buildConventionalCollaborationRecommendationMessage()
                : (
                  input.targetChapterCount == null
                    ? `请至少填写目标细化章节数或目标人物数其中一项，另一项可留空自动估算。${buildConventionalCollaborationRecommendationMessage()}`
                    : buildConventionalCollaborationRecommendationMessage()
                )
            ),
          {
            placeholder: '留空则由系统自动估算',
            min: input.currentChapterCount > CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
              ? 1
              : Math.max(1, input.currentChapterCount),
            max: getConventionalCollaborationMaxTargetChapterCount(),
            fullWidth: true,
          },
        ),
      ],
    })
    configBlocks.push({
      kind: 'fields',
      key: 'total-target-character',
      fields: [
        createField(
          'targetCharacterCount',
          '目标人物数',
          input.targetCharacterCount == null
            ? '留空后系统会结合章节需求分阶段自动估算角色补足量。'
            : '少量角色会直接补齐；较大规模角色扩展会自动改走多轮协同。',
          {
            placeholder: '留空则由系统自动估算',
            min: Math.max(1, input.currentCharacterCount),
            max: Math.max(200, input.currentCharacterCount),
            fullWidth: true,
          },
        ),
      ],
    })
  }

  const validationMessage = requestPlan.hasDelta
    ? ''
    : (
      input.expansionMode === 'volume_detail'
        ? '单卷细化协同需要先选择有效卷编号，并填写完整的本卷细化章节范围。'
        : (
          input.expansionMode === 'epic_framework'
            ? '长篇框架协同需要有效的总卷数和总章节范围。'
            : (
              input.targetChapterCount == null && input.targetCharacterCount == null
                ? '请至少填写目标细化章节数或目标人物数其中一项，留空的另一项将由系统自动估算。'
                : '目标细化章节数或目标人物数至少要有一项大于当前值，协同扩展才会执行。'
            )
        )
    )

  const currentChapterChipLabel = `当前已细化章节 ${input.currentChapterCount}`
  const currentCharacterChipLabel = `当前已识别人物 ${input.currentCharacterCount}`
  const currentCountHelperText = '当前数量按结构化内容统计：仅计算明确章节标题与已识别人物名，阶段规划、范围引用和人物关系段不计入。'

  return {
    isVolumeDetailMode,
    isLockedToVolumeDetail,
    currentChapterChipLabel,
    currentCharacterChipLabel,
    currentCountHelperText,
    displayedTargetCharacterCount,
    chapterDeltaLabel,
    chapterDeltaChipLabel,
    characterDeltaLabel,
    characterDeltaChipLabel,
    hasDelta: requestPlan.hasDelta,
    analysisWarnings: [],
    autoEstimateHints: compactAutoEstimateHints,
    hasAnalysis: !!analysis,
    precheckChips,
    analysisSummaryText: compactAnalysisSummaryText,
    modeSuitabilityView: compactModeSuitabilityView,
    intentReasonText: '',
    executionModeReasonText: '',
    writtenContextText,
    autoSupplementText: compactAutoSupplementText,
    epicConfigText,
    volumeDetailText,
    volumeCharacterPlanText,
    modelPlanLines: [],
    validationMessage,
    expansionModeHelperText: hasFramework ? '当前项目已有长篇框架，可继续单卷细化，也可以切回长篇框架协同重新生成。' : '',
    lockedModeAlertText: '',
    writtenModeInfoAlertText: isVolumeDetailMode
      ? '单卷细化协同会直接继承现有长篇框架和正文上下文，本轮不再单独配置"已写章节处理"模式。'
      : '',
    autoSupplementLabel: isVolumeDetailMode ? '允许系统自动补足本卷承接人物或桥接章节' : '允许系统自动补足配套人物或承接章节',
    configBlocks,
  }
}
