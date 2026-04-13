import type {
  StoryExpansionExecutionRound,
  StoryExpansionOutlineOperation,
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

function createChangeCardViews(input: {
  repairedMessages: string[]
  advisoryMessages: string[]
  characterPhaseMessages: string[]
  newCharacters: string[]
  stopReasons: string[]
  outlineOperationViews: StoryExpansionOutlineOperationView[]
}): StoryExpansionChangeCardView[] {
  const cards: StoryExpansionChangeCardView[] = []

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
  const outlineOperationViews = createOutlineOperationViews(outlineOps)
  const executionRoundViews = createExecutionRoundViews(executionRounds, view)
  const changeCardViews = createChangeCardViews({
    repairedMessages,
    advisoryMessages,
    characterPhaseMessages,
    newCharacters,
    stopReasons,
    outlineOperationViews,
  })
  const deltaSectionViews = createDeltaSectionViews(view)
  const finalSectionViews = createFinalSectionViews(view)
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
    executionModeReasonText,
    chapterMetricValue: formatCountDelta(chapterBefore, chapterAfter, chapterTarget),
    characterMetricValue: formatCountDelta(characterBefore, characterAfter, characterTarget),
    scoreMetricValue: `${scoreBefore} → ${scoreAfter}`,
    scoreMetricHelperText: scoreAfter >= scoreBefore ? '本轮评分保持或提升。' : '建议复查新增内容的一致性。',
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
