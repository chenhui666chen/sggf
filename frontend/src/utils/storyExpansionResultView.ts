import type {
  StoryExpansionExecutionRound,
  StoryExpansionOutlineOperation,
  StoryExpansionValidationStats,
} from '@/types/storyExpansion'
import type { StoryExpansionContentKind } from './storyExpansionResultFormatter'
import type { StoryExpansionResultView } from './storyExpansionResultModel'

const EXECUTION_ROUND_STAGE_LABELS: Record<string, string> = {
  character_expand: '人物扩展',
  epic_framework: '长篇框架生成',
  volume_detail: '单卷细化',
}

function hasText(value: string | null | undefined): boolean {
  return typeof value === 'string' && value.trim().length > 0
}

function formatDetailedChapterCount(value: number): string {
  return `${value}个细化章节`
}

function getRoundCount(view: StoryExpansionResultView | null): number {
  if (!view) {
    return 1
  }

  return view.executionRounds.length || view.outlineOps.length || 1
}

export type StoryExpansionResultSectionKey =
  | 'summary'
  | 'changes'
  | 'rounds'
  | 'delta'
  | 'outline'
  | 'characters'

export interface StoryExpansionResultQuickJumpItem {
  key: StoryExpansionResultSectionKey
  label: string
}

export interface StoryExpansionOutlineOperationView {
  key: string
  title: string
  requestedLabel: string
  generatedLabel: string
  goal: string
  generatedTitles: string[]
}

export interface StoryExpansionExecutionRoundView {
  key: string
  title: string
  strategyLabel: string | null
  chapterRangeText: string
  characterRangeText: string
  plotIncrementText: string | null
  characterIncrementText: string | null
  postValidationScoreText: string | null
}

export interface StoryExpansionResultDisplayInput {
  view: StoryExpansionResultView | null
  summaryLabel?: string | null
  writtenContextLabel?: string
  repairedMessages: string[]
  advisoryMessages: string[]
}

export interface StoryExpansionResultDisplayView {
  completionStatusLabel: string
  completionStatusTone: 'success' | 'warning' | 'default'
  completionStatusDescription: string
  remainingGoalChipLabel: string | null
  canAutoImprove: boolean
  autoImproveActionLabel: string | null
  autoImproveHint: string | null
  executionModeReasonText: string
  chapterMetricValue: string
  characterMetricValue: string
  scoreMetricValue: string
  scoreMetricHelperText: string
  roundsMetricValue: string
  roundsMetricHelperText: string
  addedChapterCount: number
  addedCharacterCount: number
  addedChapterChipLabel: string
  addedCharacterChipLabel: string
  executionRoundsChipLabel: string | null
  alignmentRepairsChipLabel: string | null
  alignmentWarningsChipLabel: string | null
  hasChangesSection: boolean
  hasDeltaSection: boolean
  quickJumpItems: StoryExpansionResultQuickJumpItem[]
  outlineOperationViews: StoryExpansionOutlineOperationView[]
  executionRoundViews: StoryExpansionExecutionRoundView[]
  changeCardViews: StoryExpansionChangeCardView[]
  deltaSectionViews: StoryExpansionDeltaSectionView[]
  finalSectionViews: StoryExpansionFinalSectionView[]
}

export type StoryExpansionChangeCardKind = 'messages' | 'chips' | 'outline_operations'
export type StoryExpansionChangeCardTone = 'success' | 'warning' | 'default'

export interface StoryExpansionChangeCardView {
  key: string
  title: string
  kind: StoryExpansionChangeCardKind
  tone: StoryExpansionChangeCardTone
  messages: string[]
  chips: string[]
  outlineOperations: StoryExpansionOutlineOperationView[]
}

export interface StoryExpansionDeltaSectionView {
  key: string
  title: string
  content: string
  contentKind: StoryExpansionContentKind
  copyMessage: string
}

export interface StoryExpansionFinalSectionView {
  key: 'outline' | 'characters'
  title: string
  content: string
  contentKind: StoryExpansionContentKind
  copyMessage: string
  lg: 5 | 7
}

export function getOutlineOperationLabel(op: StoryExpansionOutlineOperation): string {
  if (op?.action === 'insert_after') {
    return `插入到第 ${op.after_chapter ?? '?'} 章后`
  }

  return '追加到大纲末尾'
}

export function getExecutionRoundTitle(round: StoryExpansionExecutionRound, index: number): string {
  if (typeof round?.round === 'number') {
    return `第 ${round.round} 轮协同`
  }

  if (typeof round?.stage === 'string') {
    return `${EXECUTION_ROUND_STAGE_LABELS[round.stage] || round.stage} ${index + 1}`
  }

  return `执行轮次 ${index + 1}`
}

export function formatCountDelta(before: number, after: number, target: number): string {
  const base = `${before} → ${after}`
  if (target > 0) {
    return `${base} / 目标 ${target}`
  }

  return base
}

function formatRemainingGoalText(chapterGap: number, characterGap: number): string {
  const parts: string[] = []
  if (chapterGap > 0) {
    parts.push(`${chapterGap} 章`)
  }
  if (characterGap > 0) {
    parts.push(`${characterGap} 人`)
  }
  return parts.length > 0 ? `仍差 ${parts.join(' / ')}` : ''
}

function resolveCompletionStatusPresentation(view: StoryExpansionResultView | null): {
  label: string
  tone: 'success' | 'warning' | 'default'
  description: string
  remainingGoalChipLabel: string | null
} {
  if (!view) {
    return {
      label: '结果待确认',
      tone: 'default',
      description: '当前结果将根据目标达成情况自动标记为已达目标或阶段性完成。',
      remainingGoalChipLabel: null,
    }
  }

  if (view.result.execution_mode === 'repair') {
    return {
      label: '修复完成',
      tone: 'success',
      description: '当前结果来自定向修复，不会自动开启下一轮协同扩展。',
      remainingGoalChipLabel: null,
    }
  }

  const remainingGoalText = formatRemainingGoalText(
    view.remainingChapterCount,
    view.remainingCharacterCount,
  )

  if (!view.goalReached || view.completionStatus === 'partial') {
    return {
      label: '阶段性完成',
      tone: 'warning',
      description: remainingGoalText
        ? `本次协同已完成当前可确认增量，${remainingGoalText}。`
        : '本次协同已阶段性收口，但仍需结合结果判断是否继续补齐目标。',
      remainingGoalChipLabel: remainingGoalText || null,
    }
  }

  return {
    label: '已达目标',
    tone: 'success',
    description: '本次协同已达到当前设定的章节与人物目标。',
    remainingGoalChipLabel: null,
  }
}

function createOutlineOperationViews(
  outlineOps: StoryExpansionOutlineOperation[],
): StoryExpansionOutlineOperationView[] {
  return outlineOps.map((op, index) => ({
    key: `${op.action || 'append'}-${index}`,
    title: getOutlineOperationLabel(op),
    requestedLabel: `计划 ${formatDetailedChapterCount(op.requested_count ?? 0)}`,
    generatedLabel: `实际 ${formatDetailedChapterCount(op.generated_count ?? 0)}`,
    goal: hasText(op.goal) ? op.goal!.trim() : '',
    generatedTitles: Array.isArray(op.generated_titles)
      ? op.generated_titles.filter((title): title is string => hasText(title))
      : [],
  }))
}

function createExecutionRoundViews(
  executionRounds: StoryExpansionExecutionRound[],
  view: StoryExpansionResultView | null,
): StoryExpansionExecutionRoundView[] {
  const fallbackChapterBefore = view?.chapterBefore ?? 0
  const fallbackChapterAfter = view?.chapterAfter ?? 0
  const fallbackCharacterBefore = view?.characterBefore ?? 0
  const fallbackCharacterAfter = view?.characterAfter ?? 0

  return executionRounds.map((round, index) => ({
    key: `${round?.round || round?.stage || 'round'}-${index}`,
    title: getExecutionRoundTitle(round, index),
    strategyLabel: hasText(round?.strategy) ? `策略：${round.strategy!.trim()}` : null,
    chapterRangeText: `细化章节：${round?.before_chapter_count ?? fallbackChapterBefore} → ${round?.after_chapter_count ?? fallbackChapterAfter}`,
    characterRangeText: `人物：${round?.before_character_count ?? fallbackCharacterBefore} → ${round?.after_character_count ?? fallbackCharacterAfter}`,
    plotIncrementText:
      typeof round?.plot?.increment_requested === 'number' && round.plot.increment_requested > 0
        ? `本轮新增目标：${formatDetailedChapterCount(round.plot.increment_requested)}`
        : null,
    characterIncrementText:
      typeof round?.character?.increment_requested === 'number' && round.character.increment_requested > 0
        ? `本轮新增人物目标：${round.character.increment_requested}`
        : null,
    postValidationScoreText:
      typeof round?.character?.post_validation_score === 'number'
        ? `人物匹配评分：${round.character.post_validation_score}`
        : null,
  }))
}

function createCharacterPhaseMessages(view: StoryExpansionResultView | null): string[] {
  const characterPlan = view?.result.expansion_analysis?.auto_supplement?.character_plan
  const recommendedRangeText = hasText(characterPlan?.recommended_range_text)
    ? characterPlan!.recommended_range_text!.trim()
    : ''
  const stageLabel = hasText(characterPlan?.stage_label)
    ? characterPlan!.stage_label!.trim()
    : ''
  const stageTarget = typeof characterPlan?.stage_target_characters === 'number'
    ? Math.max(0, characterPlan.stage_target_characters)
    : 0
  const taskTarget = typeof characterPlan?.task_target_characters === 'number'
    ? Math.max(0, characterPlan.task_target_characters)
    : 0
  const taskTargetIncrement = typeof characterPlan?.task_target_increment === 'number'
    ? Math.max(0, characterPlan.task_target_increment)
    : 0
  const suggestedIncrement = typeof characterPlan?.suggested_increment === 'number'
    ? Math.max(0, characterPlan.suggested_increment)
    : 0
  const remainingToFloor = typeof characterPlan?.remaining_to_recommended_min === 'number'
    ? Math.max(0, characterPlan.remaining_to_recommended_min)
    : 0
  const followUpPhase = hasText(characterPlan?.follow_up_phase)
    ? characterPlan!.follow_up_phase!.trim()
    : ''

  if (!recommendedRangeText || !stageLabel || stageTarget <= 0) {
    return []
  }

  const messages = [
    `全书建议规模约为 ${recommendedRangeText} 人，${stageLabel}先补到 ${stageTarget} 人${suggestedIncrement > 0 ? `（本次新增 ${suggestedIncrement} 人）` : ''}。`,
  ]
  if (taskTarget > stageTarget) {
    messages.push(`点击一次开始后，系统会自动连续执行多轮；首轮人物数只是起点，不是整次任务上限。`)
    messages.push(
      taskTargetIncrement > 0
        ? `本次自动协同预计补到 ${taskTarget} 人（约新增 ${taskTargetIncrement} 人）。`
        : `本次自动协同预计补到 ${taskTarget} 人。`,
    )
  }
  if (remainingToFloor > 0 && followUpPhase) {
    messages.push(`距离建议下限还差约 ${remainingToFloor} 人，会在${followUpPhase}继续补齐。`)
  }
  return messages
}

function collectUniqueMessages(messages: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const result: string[] = []

  for (const raw of messages) {
    if (!hasText(raw)) {
      continue
    }

    const text = raw!.trim()
    if (seen.has(text)) {
      continue
    }

    seen.add(text)
    result.push(text)
  }

  return result
}

function normalizeSuggestionText(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) {
    return ''
  }

  return trimmed
    .replace(/^[\-\*•·]\s*/u, '')
    .replace(/^\d+[\.\)\]、．]\s*/u, '')
    .trim()
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '0%'
  }

  const normalized = value <= 1 ? value * 100 : value
  return `${Math.round(normalized)}%`
}

function formatCharacterList(names: string[], limit = 4): string {
  if (names.length <= 0) {
    return '相关人物'
  }

  if (names.length <= limit) {
    return names.join('、')
  }

  return `${names.slice(0, limit).join('、')} 等 ${names.length} 人`
}

function getValidationSuggestions(validation: StoryExpansionValidationStats | undefined): string[] {
  return collectUniqueMessages(
    (validation?.suggestions ?? []).map((item) => normalizeSuggestionText(item)),
  ).filter((item) => item !== '当前人物与大纲的基础协同正常，适合继续做增量扩展。')
}

function createScoreRegressionReasonLines(view: StoryExpansionResultView | null): string[] {
  const before = view?.result.validation_before
  const after = view?.result.validation_after
  const scoreBefore = view?.scoreBefore ?? 0
  const scoreAfter = view?.scoreAfter ?? 0

  if (!after || scoreAfter >= scoreBefore) {
    return []
  }

  const reasons: string[] = []
  const unreferencedCharacters = after.unreferenced_characters ?? []
  if (unreferencedCharacters.length > 0) {
    reasons.push(`仍有未被章节正式承接的人物：${formatCharacterList(unreferencedCharacters)}。`)
  }

  const coverageBefore = typeof before?.coverage_ratio === 'number' ? before.coverage_ratio : null
  const coverageAfter = typeof after.coverage_ratio === 'number' ? after.coverage_ratio : null
  if (
    coverageBefore != null
    && coverageAfter != null
    && coverageAfter < coverageBefore
  ) {
    reasons.push(
      `人物覆盖率从 ${formatPercent(coverageBefore)} 降到 ${formatPercent(coverageAfter)}，新增内容对人物挂接不足。`,
    )
  }

  const referencedBefore = before?.referenced_characters?.length ?? 0
  const referencedAfter = after.referenced_characters?.length ?? 0
  const chapterBefore = before?.chapter_count ?? view?.chapterBefore ?? 0
  const chapterAfter = after.chapter_count ?? view?.chapterAfter ?? 0
  if (chapterAfter > chapterBefore && referencedAfter <= referencedBefore) {
    reasons.push('章节数增加了，但被正式挂接的人物没有同步增加，说明本轮偏向扩剧情、弱化了人物承接。')
  }

  if (reasons.length > 0) {
    return collectUniqueMessages(reasons)
  }

  const fallbackSuggestions = getValidationSuggestions(after)
  if (fallbackSuggestions.length > 0) {
    return [`评分回落后，当前最优先修补项是：${fallbackSuggestions[0]}`]
  }

  return ['协同评分下降，说明新增章节与人物设定之间出现了新的挂接缺口。']
}

function createActionableImprovementLines(view: StoryExpansionResultView | null): string[] {
  const after = view?.result.validation_after
  if (!after) {
    return []
  }

  const improvements: string[] = []
  const unreferencedCharacters = after.unreferenced_characters ?? []
  if (unreferencedCharacters.length > 0) {
    improvements.push(
      `优先把 ${formatCharacterList(unreferencedCharacters)} 补进对应章节的“涉及人物”字段，并明确这些角色在该章承担的剧情职责。`,
    )
  }

  const suggestions = getValidationSuggestions(after)
  improvements.push(...suggestions)

  const coverageRatio = typeof after.coverage_ratio === 'number' ? after.coverage_ratio : null
  if (coverageRatio != null && coverageRatio < 0.6) {
    improvements.push('复查新增章节的“涉及人物”“人物推进”“情节作用”三项，避免只有事件推进、没有人物挂接。')
  }

  if ((after.referenced_characters?.length ?? 0) <= 0 && (after.character_count ?? 0) > 0) {
    improvements.push('至少先让关键角色进入章节正文字段，再继续做后续内容扩写。')
  }

  const scoreBefore = view?.scoreBefore ?? 0
  const scoreAfter = view?.scoreAfter ?? 0
  if (scoreAfter < scoreBefore) {
    improvements.push('先修复当前章节的人物承接，再决定是否继续追加新章节或新角色。')
  }

  return collectUniqueMessages(improvements)
}

function createScoreMetricHelperText(view: StoryExpansionResultView | null): string {
  const scoreBefore = view?.scoreBefore ?? 0
  const scoreAfter = view?.scoreAfter ?? 0
  if (scoreAfter >= scoreBefore) {
    return '本轮评分保持或提升。'
  }

  const diff = Math.max(0, scoreBefore - scoreAfter)
  const reasons = createScoreRegressionReasonLines(view)
  if (reasons.length > 0) {
    return `下降 ${diff} 分。${reasons[0]}`
  }

  return `下降 ${diff} 分，建议先修复人物与章节的挂接缺口。`
}

function createChangeCardViews(input: {
  scoreRegressionReasonLines: string[]
  actionableImprovementLines: string[]
  repairedMessages: string[]
  advisoryMessages: string[]
  characterPhaseMessages: string[]
  newCharacters: string[]
  stopReasons: string[]
  outlineOperationViews: StoryExpansionOutlineOperationView[]
}): StoryExpansionChangeCardView[] {
  const cards: StoryExpansionChangeCardView[] = []

  if (input.scoreRegressionReasonLines.length > 0) {
    cards.push({
      key: 'score-regression-reasons',
      title: '评分下降原因',
      kind: 'messages',
      tone: 'warning',
      messages: input.scoreRegressionReasonLines,
      chips: [],
      outlineOperations: [],
    })
  }

  if (input.actionableImprovementLines.length > 0) {
    cards.push({
      key: 'score-improvements',
      title: '建议优先修复',
      kind: 'messages',
      tone: 'default',
      messages: input.actionableImprovementLines,
      chips: [],
      outlineOperations: [],
    })
  }

  if (input.repairedMessages.length > 0) {
    cards.push({
      key: 'repairs',
      title: '自动修复',
      kind: 'messages',
      tone: 'success',
      messages: input.repairedMessages,
      chips: [],
      outlineOperations: [],
    })
  }

  if (input.advisoryMessages.length > 0) {
    cards.push({
      key: 'advisories',
      title: '协同提醒',
      kind: 'messages',
      tone: 'warning',
      messages: input.advisoryMessages,
      chips: [],
      outlineOperations: [],
    })
  }

  if (input.characterPhaseMessages.length > 0) {
    cards.push({
      key: 'character-phase-plan',
      title: '阶段人物计划',
      kind: 'messages',
      tone: 'default',
      messages: input.characterPhaseMessages,
      chips: [],
      outlineOperations: [],
    })
  }

  if (input.newCharacters.length > 0) {
    cards.push({
      key: 'new-characters',
      title: '本轮新增角色',
      kind: 'chips',
      tone: 'default',
      messages: [],
      chips: input.newCharacters,
      outlineOperations: [],
    })
  }

  if (input.stopReasons.length > 0) {
    cards.push({
      key: 'stop-reasons',
      title: '停止原因',
      kind: 'messages',
      tone: 'default',
      messages: input.stopReasons,
      chips: [],
      outlineOperations: [],
    })
  }

  if (input.outlineOperationViews.length > 0) {
    cards.push({
      key: 'outline-operations',
      title: '本轮细化章节操作',
      kind: 'outline_operations',
      tone: 'default',
      messages: [],
      chips: [],
      outlineOperations: input.outlineOperationViews,
    })
  }

  return cards
}

function createDeltaSectionViews(view: StoryExpansionResultView | null): StoryExpansionDeltaSectionView[] {
  const sections: StoryExpansionDeltaSectionView[] = []

  if (hasText(view?.outlineDelta)) {
    sections.push({
      key: 'outline-delta',
      title: '细化章节增量',
      content: view!.outlineDelta,
      contentKind: 'delta',
      copyMessage: '已复制细化章节增量',
    })
  }

  if (hasText(view?.characterDelta)) {
    sections.push({
      key: 'character-delta',
      title: '人物增量',
      content: view!.characterDelta,
      contentKind: 'character',
      copyMessage: '已复制人物增量',
    })
  }

  if (hasText(view?.characterRelationships)) {
    sections.push({
      key: 'relationship-delta',
      title: '关系补丁',
      content: view!.characterRelationships,
      contentKind: 'relationship',
      copyMessage: '已复制关系补丁',
    })
  }

  return sections
}

function createFinalSectionViews(view: StoryExpansionResultView | null): StoryExpansionFinalSectionView[] {
  return [
    {
      key: 'outline',
      title: '更新后大纲',
      content: view?.expandedOutline ?? '',
      contentKind: 'outline',
      copyMessage: '已复制更新后大纲',
      lg: 7,
    },
    {
      key: 'characters',
      title: '更新后人物',
      content: view?.allCharacters ?? '',
      contentKind: 'character',
      copyMessage: '已复制更新后人物',
      lg: 5,
    },
  ]
}

export function createStoryExpansionResultDisplayView(
  input: StoryExpansionResultDisplayInput,
): StoryExpansionResultDisplayView {
  const view = input.view
  const chapterBefore = view?.chapterBefore ?? 0
  const chapterAfter = view?.chapterAfter ?? 0
  const chapterTarget = view?.chapterTarget ?? chapterAfter
  const characterBefore = view?.characterBefore ?? 0
  const characterAfter = view?.characterAfter ?? 0
  const characterTarget = view?.characterTarget ?? characterAfter
  const scoreBefore = view?.scoreBefore ?? 0
  const scoreAfter = view?.scoreAfter ?? 0
  const executionRounds = view?.executionRounds ?? []
  const outlineOps = view?.outlineOps ?? []
  const newCharacters = view?.newCharacters ?? []
  const stopReasons = view?.stopReasons ?? []
  const repairedMessages = input.repairedMessages
  const advisoryMessages = input.advisoryMessages
  const characterPhaseMessages = createCharacterPhaseMessages(view)
  const scoreRegressionReasonLines = createScoreRegressionReasonLines(view)
  const actionableImprovementLines = createActionableImprovementLines(view)
  const outlineOperationViews = createOutlineOperationViews(outlineOps)
  const executionRoundViews = createExecutionRoundViews(executionRounds, view)
  const changeCardViews = createChangeCardViews({
    scoreRegressionReasonLines,
    actionableImprovementLines,
    repairedMessages,
    advisoryMessages,
    characterPhaseMessages,
    newCharacters,
    stopReasons,
    outlineOperationViews,
  })
  const deltaSectionViews = createDeltaSectionViews(view)
  const finalSectionViews = createFinalSectionViews(view)
  const completionStatusPresentation = resolveCompletionStatusPresentation(view)
  const isRepairResult = view?.result.execution_mode === 'repair'
  const canAutoImprove = !isRepairResult && (
    scoreRegressionReasonLines.length > 0
    || actionableImprovementLines.length > 0
  )
  const executionModeReasonText = hasText(view?.executionModeReason)
    ? view!.executionModeReason.trim()
    : '本次结果已按可扫描的摘要、增量和最终内容分区展示。'
  const hasChangesSection = (
    changeCardViews.length > 0
  )
  const hasDeltaSection = (
    deltaSectionViews.length > 0
  )
  const quickJumpItems: StoryExpansionResultQuickJumpItem[] = []

  if (hasText(input.summaryLabel)) {
    quickJumpItems.push({ key: 'summary', label: input.summaryLabel!.trim() })
  }
  if (hasChangesSection) {
    quickJumpItems.push({ key: 'changes', label: '本轮变更' })
  }
  if (executionRounds.length > 0) {
    quickJumpItems.push({ key: 'rounds', label: '协同轮次' })
  }
  if (hasDeltaSection) {
    quickJumpItems.push({ key: 'delta', label: '增量内容' })
  }
  finalSectionViews
    .filter((section) => hasText(section.content))
    .forEach((section) => {
      quickJumpItems.push({ key: section.key, label: section.title })
    })

  return {
    completionStatusLabel: completionStatusPresentation.label,
    completionStatusTone: completionStatusPresentation.tone,
    completionStatusDescription: completionStatusPresentation.description,
    remainingGoalChipLabel: completionStatusPresentation.remainingGoalChipLabel,
    canAutoImprove,
    autoImproveActionLabel: canAutoImprove ? '一键自动改进' : null,
    autoImproveHint: canAutoImprove
      ? '系统会根据当前协同结果自动补齐人物承接与章节挂接，不会开启下一轮协同。'
      : null,
    executionModeReasonText,
    chapterMetricValue: formatCountDelta(chapterBefore, chapterAfter, chapterTarget),
    characterMetricValue: formatCountDelta(characterBefore, characterAfter, characterTarget),
    scoreMetricValue: `${scoreBefore} → ${scoreAfter}`,
    scoreMetricHelperText: createScoreMetricHelperText(view),
    roundsMetricValue: `${getRoundCount(view)} 轮`,
    roundsMetricHelperText: input.writtenContextLabel
      ? `正文处理策略：${input.writtenContextLabel}`
      : '未额外覆盖正文处理策略。',
    addedChapterCount: view?.addedChapterCount ?? 0,
    addedCharacterCount: view?.addedCharacterCount ?? 0,
    addedChapterChipLabel: `本轮新增 ${formatDetailedChapterCount(view?.addedChapterCount ?? 0)}`,
    addedCharacterChipLabel: `本轮新增人物 ${view?.addedCharacterCount ?? 0} 人`,
    executionRoundsChipLabel: executionRounds.length > 0 ? `共执行 ${executionRounds.length} 轮` : null,
    alignmentRepairsChipLabel: repairedMessages.length > 0 ? `已自动修复 ${repairedMessages.length} 处人物承接` : null,
    alignmentWarningsChipLabel: advisoryMessages.length > 0 ? `存在 ${advisoryMessages.length} 条协同提醒` : null,
    hasChangesSection,
    hasDeltaSection,
    quickJumpItems,
    outlineOperationViews,
    executionRoundViews,
    changeCardViews,
    deltaSectionViews,
    finalSectionViews,
  }
}
