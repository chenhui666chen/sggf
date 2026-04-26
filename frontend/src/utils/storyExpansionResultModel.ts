import type {
  StoryExpansionCompletionStatus,
  StoryExpansionCharacterSync,
  StoryExpansionExecutionRound,
  StoryExpansionOutlineOperation,
  StoryExpansionResult,
  StoryExpansionValidationStats,
  StoryExpansionWrittenContext,
} from '@/types/storyExpansion'

type UnknownRecord = Record<string, unknown>

function asRecord(value: unknown): UnknownRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  return value as UnknownRecord
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value.trim() : undefined
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function asInteger(value: unknown): number | undefined {
  const numberValue = asNumber(value)
  return typeof numberValue === 'number' ? Math.trunc(numberValue) : undefined
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function coerceStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }

  const seen = new Set<string>()
  const result: string[] = []
  for (const item of value) {
    const text = asString(item)
    if (!text || seen.has(text)) {
      continue
    }
    seen.add(text)
    result.push(text)
  }
  return result
}

function coerceNumberArray(value: unknown): number[] | undefined {
  if (!Array.isArray(value)) {
    return undefined
  }

  const result = value
    .map((item) => asInteger(item))
    .filter((item): item is number => typeof item === 'number')

  return result.length > 0 ? result : undefined
}

function coerceWrittenContext(value: unknown): StoryExpansionWrittenContext | undefined {
  const record = asRecord(value)
  if (!record) {
    return undefined
  }

  return {
    applied: typeof record.applied === 'boolean' ? record.applied : undefined,
    written_chapter_count: asInteger(record.written_chapter_count),
    preserve_written_mode: asString(record.preserve_written_mode),
    preview: asString(record.preview),
  }
}

function coerceValidationStats(value: unknown): StoryExpansionValidationStats | undefined {
  const record = asRecord(value)
  if (!record) {
    return undefined
  }

  return {
    score: asNumber(record.score),
    coverage_ratio: asNumber(record.coverage_ratio),
    unreferenced_characters: coerceStringArray(record.unreferenced_characters),
    referenced_characters: coerceStringArray(record.referenced_characters),
    chapter_count: asInteger(record.chapter_count),
    character_count: asInteger(record.character_count),
    suggestions: coerceStringArray(record.suggestions),
    validation_stage: asString(record.validation_stage),
  }
}

function coerceOutlineOperation(value: unknown): StoryExpansionOutlineOperation | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  return {
    action: asString(record.action),
    after_chapter: asInteger(record.after_chapter) ?? null,
    requested_count: asInteger(record.requested_count) ?? null,
    generated_count: asInteger(record.generated_count) ?? null,
    goal: asString(record.goal),
    generated_titles: coerceStringArray(record.generated_titles),
  }
}

function coerceExecutionRound(value: unknown): StoryExpansionExecutionRound | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const plot = asRecord(record.plot)
  const character = asRecord(record.character)

  return {
    round: asInteger(record.round),
    stage: asString(record.stage),
    strategy: asString(record.strategy),
    before_chapter_count: asInteger(record.before_chapter_count),
    after_chapter_count: asInteger(record.after_chapter_count),
    before_character_count: asInteger(record.before_character_count),
    after_character_count: asInteger(record.after_character_count),
    plot: plot ? { increment_requested: asInteger(plot.increment_requested) ?? null } : undefined,
    character: character
      ? {
        increment_requested: asInteger(character.increment_requested) ?? null,
        post_validation_score: asNumber(character.post_validation_score) ?? null,
        cards_response_mode: asString(character.cards_response_mode),
        cards_retry_used:
          typeof character.cards_retry_used === 'boolean' ? character.cards_retry_used : undefined,
        recognized_new_character_count: asInteger(character.recognized_new_character_count) ?? null,
        recognized_new_character_names: coerceStringArray(character.recognized_new_character_names),
      }
      : undefined,
  }
}

function coerceCharacterSync(value: unknown): StoryExpansionCharacterSync | undefined {
  const record = asRecord(value)
  if (!record) {
    return undefined
  }

  const relationships = asRecord(record.relationships)

  return {
    parsed: asInteger(record.parsed),
    created: asInteger(record.created),
    updated: asInteger(record.updated),
    skipped: asInteger(record.skipped),
    relationships: relationships
      ? {
        parsed: asInteger(relationships.parsed),
        saved: asInteger(relationships.saved),
        characters_updated: asInteger(relationships.characters_updated),
      }
      : undefined,
  }
}

export interface StoryExpansionResultView {
  result: StoryExpansionResult
  completionStatus: StoryExpansionCompletionStatus | string
  goalReached: boolean
  chapterBefore: number
  chapterAfter: number
  chapterTarget: number
  remainingChapterCount: number
  characterBefore: number
  characterAfter: number
  characterTarget: number
  remainingCharacterCount: number
  scoreBefore: number
  scoreAfter: number
  executionRounds: StoryExpansionExecutionRound[]
  outlineOps: StoryExpansionOutlineOperation[]
  newCharacters: string[]
  alignmentRepairs: string[]
  alignmentWarnings: string[]
  stopReasons: string[]
  executionModeReason: string
  outlineDelta: string
  characterDelta: string
  characterRelationships: string
  expandedOutline: string
  allCharacters: string
  addedChapterCount: number
  addedCharacterCount: number
}

export function coerceStoryExpansionResult(value: unknown): StoryExpansionResult | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const expansionAnalysis = asRecord(record.expansion_analysis)

  return {
    expanded_outline: asString(record.expanded_outline) || '',
    all_characters: asString(record.all_characters) || '',
    outline_delta: asString(record.outline_delta) || '',
    character_delta: asString(record.character_delta) || '',
    character_relationships: asString(record.character_relationships) || '',
    outline_ops: Array.isArray(record.outline_ops)
      ? record.outline_ops
        .map((item) => coerceOutlineOperation(item))
        .filter((item): item is StoryExpansionOutlineOperation => item !== null)
      : [],
    execution_mode: asString(record.execution_mode),
    execution_mode_reason: asString(record.execution_mode_reason),
    execution_rounds: Array.isArray(record.execution_rounds)
      ? record.execution_rounds
        .map((item) => coerceExecutionRound(item))
        .filter((item): item is StoryExpansionExecutionRound => item !== null)
      : [],
    new_characters: coerceStringArray(record.new_characters),
    alignment_repairs: coerceStringArray(record.alignment_repairs),
    story_strategy: asString(record.story_strategy),
    story_intent: asString(record.story_intent),
    story_expansion_mode: asString(record.story_expansion_mode),
    story_preserve_written_mode: asString(record.story_preserve_written_mode),
    written_chapter_context: coerceWrittenContext(record.written_chapter_context),
    volume_index: asInteger(record.volume_index) ?? null,
    volume_chapter_range: coerceNumberArray(record.volume_chapter_range) ?? null,
    coordination_summary: asString(record.coordination_summary),
    current_chapter_count: asInteger(record.current_chapter_count),
    target_chapter_count: asInteger(record.target_chapter_count),
    current_character_count: asInteger(record.current_character_count),
    target_character_count: asInteger(record.target_character_count),
    validation_before: coerceValidationStats(record.validation_before),
    validation_after: coerceValidationStats(record.validation_after),
    alignment_warnings: coerceStringArray(record.alignment_warnings),
    character_sync: coerceCharacterSync(record.character_sync),
    stop_reasons: coerceStringArray(record.stop_reasons),
    expansion_analysis: expansionAnalysis ? (expansionAnalysis as StoryExpansionResult['expansion_analysis']) : undefined,
    epic_total_volumes: asInteger(record.epic_total_volumes) ?? null,
    epic_chapter_range: coerceNumberArray(record.epic_chapter_range) ?? null,
    completion_status: asString(record.completion_status),
    goal_reached: asBoolean(record.goal_reached),
    message: asString(record.message),
  }
}

export function createStoryExpansionResultView(
  result: StoryExpansionResult | null | undefined,
): StoryExpansionResultView | null {
  const normalized = coerceStoryExpansionResult(result)
  if (!normalized) {
    return null
  }

  const chapterBefore = normalized.validation_before?.chapter_count ?? 0
  const chapterAfter = normalized.current_chapter_count ?? 0
  const chapterTarget = normalized.target_chapter_count ?? chapterAfter
  const remainingChapterCount = Math.max(0, chapterTarget - chapterAfter)
  const characterBefore = normalized.validation_before?.character_count ?? 0
  const characterAfter = normalized.current_character_count ?? 0
  const characterTarget = normalized.target_character_count ?? characterAfter
  const remainingCharacterCount = Math.max(0, characterTarget - characterAfter)
  const inferredGoalReached = remainingChapterCount <= 0 && remainingCharacterCount <= 0
  const goalReached = typeof normalized.goal_reached === 'boolean'
    ? normalized.goal_reached
    : inferredGoalReached
  const completionStatus = normalized.completion_status?.trim()
    || (goalReached ? 'completed' : 'partial')
  const scoreBefore = normalized.validation_before?.score ?? 0
  const scoreAfter = normalized.validation_after?.score ?? 0

  return {
    result: normalized,
    completionStatus,
    goalReached,
    chapterBefore,
    chapterAfter,
    chapterTarget,
    remainingChapterCount,
    characterBefore,
    characterAfter,
    characterTarget,
    remainingCharacterCount,
    scoreBefore,
    scoreAfter,
    executionRounds: normalized.execution_rounds ?? [],
    outlineOps: normalized.outline_ops ?? [],
    newCharacters: normalized.new_characters ?? [],
    alignmentRepairs: normalized.alignment_repairs ?? [],
    alignmentWarnings: normalized.alignment_warnings ?? [],
    stopReasons: normalized.stop_reasons ?? [],
    executionModeReason: normalized.execution_mode_reason?.trim() || '',
    outlineDelta: normalized.outline_delta || '',
    characterDelta: normalized.character_delta || '',
    characterRelationships: normalized.character_relationships || '',
    expandedOutline: normalized.expanded_outline || '',
    allCharacters: normalized.all_characters || '',
    addedChapterCount: Math.max(0, chapterAfter - chapterBefore),
    addedCharacterCount: Math.max(0, characterAfter - characterBefore),
  }
}
