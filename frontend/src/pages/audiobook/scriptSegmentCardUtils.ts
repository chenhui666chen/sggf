import type {
  AudioAssetSelection,
  InlineTagStrategySummary,
  ScriptSegment,
  ScriptSegmentVoiceParams,
} from './types'
import type { TranslateFn } from './audioLibraryDisplay'
import { modelUsesBasicNumericSpeedControl } from './ttsModels'

export const parseOptionalNumberInput = (value: string): number | null => {
  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

export const parseCommaSeparatedList = (value: string): string[] =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)

const FIXED_VOICE_IDENTITY_CONTROL_KEYS = new Set([
  'pitch',
  'pitch_ratio',
  'pitch_semitones',
  'character_base_pitch',
  'voice_description',
  'voice_design_prompt',
])

const NUMERIC_SPEED_CONTROL_KEYS = new Set([
  'speed',
  'rate',
  'character_base_speed',
])

const sanitizeVoiceControlValue = (
  value: unknown,
  allowNumericSpeed: boolean,
): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeVoiceControlValue(item, allowNumericSpeed))
  }
  if (!value || typeof value !== 'object') {
    return value
  }
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) =>
        !FIXED_VOICE_IDENTITY_CONTROL_KEYS.has(key)
        && (allowNumericSpeed || !NUMERIC_SPEED_CONTROL_KEYS.has(key)),
      )
      .map(([key, nestedValue]) => [
        key,
        sanitizeVoiceControlValue(nestedValue, allowNumericSpeed),
      ]),
  )
}

const voiceParamsAllowNumericSpeed = (voiceParams: unknown): boolean => {
  if (!voiceParams || typeof voiceParams !== 'object') {
    return false
  }
  const params = voiceParams as Record<string, unknown>
  return modelUsesBasicNumericSpeedControl(
    params.resolved_tts_model || params.tts_model,
  )
}

export const sanitizeScriptSegmentVoiceParams = (
  voiceParams: unknown,
): ScriptSegmentVoiceParams =>
  voiceParams && typeof voiceParams === 'object'
    ? sanitizeVoiceControlValue(
        voiceParams,
        voiceParamsAllowNumericSpeed(voiceParams),
      ) as ScriptSegmentVoiceParams
    : {}

export const sanitizeScriptSegmentVoiceIdentityControls = <
  T extends Partial<ScriptSegment>,
>(segment: T): T => {
  const allowNumericSpeed = voiceParamsAllowNumericSpeed(segment.voice_params)
  const sanitized = Object.fromEntries(
    Object.entries(segment)
      .filter(([key]) =>
        !FIXED_VOICE_IDENTITY_CONTROL_KEYS.has(key)
        && (allowNumericSpeed || !NUMERIC_SPEED_CONTROL_KEYS.has(key)),
      )
      .map(([key, value]) => [
        key,
        key === 'voice_params' && value !== null
          ? sanitizeScriptSegmentVoiceParams(value)
          : value,
      ]),
  )
  return sanitized as T
}

export const getScriptSegmentVoiceParams = (
  segment: Pick<ScriptSegment, 'voice_params'>,
): ScriptSegmentVoiceParams => sanitizeScriptSegmentVoiceParams(segment.voice_params)

const normalizeText = (value: unknown): string => (typeof value === 'string' ? value.trim() : '')

export const buildSoundEffectAssetPatch = (
  selection: AudioAssetSelection,
): Pick<ScriptSegment, 'sound_effects' | 'sound_effects_simple'> => ({
  ...appendSoundEffectAssetPatch({}, selection),
})

export const appendSoundEffectAssetPatch = (
  segment: Pick<ScriptSegment, 'sound_effects_simple' | 'sound_effects'>,
  selection: AudioAssetSelection,
  description?: string,
): Pick<ScriptSegment, 'sound_effects' | 'sound_effects_simple'> => {
  const effects: Array<Record<string, unknown>> = []
  const seenAssetIds = new Set<string>()
  const append = (raw: unknown) => {
    if (typeof raw === 'string') {
      const name = normalizeText(raw)
      if (name) effects.push({ name })
      return
    }
    if (!raw || typeof raw !== 'object') return
    const item = { ...(raw as Record<string, unknown>) }
    const assetId = normalizeText(item.asset_id || item.id || item.effect_id)
    if (assetId && seenAssetIds.has(assetId)) return
    if (assetId) seenAssetIds.add(assetId)
    const name = normalizeText(item.name || item.effect_id || item.id || item.asset_id)
    if (name || assetId) effects.push({ ...item, ...(name ? { name } : {}) })
  }

  ;(Array.isArray(segment.sound_effects) ? segment.sound_effects : []).forEach(append)
  ;(Array.isArray(segment.sound_effects_simple) ? segment.sound_effects_simple : []).forEach(append)

  const assetId = normalizeText(selection.id)
  const selectedName = normalizeText(description)
    || normalizeText(selection.name)
    || normalizeText(selection.label)
    || assetId
  const selectedIndex = assetId
    ? effects.findIndex((item) => normalizeText(item.asset_id || item.id || item.effect_id) === assetId)
    : -1
  const selectedItem = { asset_id: assetId, name: selectedName }
  if (selectedIndex >= 0) {
    effects[selectedIndex] = { ...effects[selectedIndex], ...selectedItem }
  } else if (assetId || selectedName) {
    effects.push(selectedItem)
  }

  return {
    sound_effects: effects as ScriptSegment['sound_effects'],
    sound_effects_simple: [],
  }
}

export const buildMusicAssetPatch = (
  selection: AudioAssetSelection,
): Pick<ScriptSegment, 'music_cue' | 'music_cue_simple'> => {
  const label = normalizeText(selection.label)
  const style = normalizeText(selection.style) || label || normalizeText(selection.id)
  const mood = normalizeText(selection.mood)
  return {
    music_cue: {
      asset_id: normalizeText(selection.id),
      style,
      name: label || style,
      ...(mood ? { mood } : {}),
    },
    music_cue_simple: null,
  }
}

const normalizeTextList = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }
  const result: string[] = []
  const seen = new Set<string>()
  value.forEach((item) => {
    const text = normalizeText(item)
    if (!text || seen.has(text)) {
      return
    }
    result.push(text)
    seen.add(text)
  })
  return result
}

export const getInlineTagStrategySummary = (
  segment: Pick<ScriptSegment, 'voice_params'>,
): InlineTagStrategySummary | null => {
  const strategy = segment.voice_params
    ?.provider_prompt_snapshot
    ?.provider_prompt
    ?.inline_tag_strategy
  if (!strategy || typeof strategy !== 'object') {
    return null
  }

  const tags = normalizeTextList([
    ...normalizeTextList(strategy.style_tags),
    ...normalizeTextList(strategy.inline_tags),
  ])
  const modelFamily = normalizeText(strategy.model_family)
  const placement = normalizeText(strategy.placement)
  if (!modelFamily && !placement && tags.length === 0) {
    return null
  }

  return {
    modelFamily,
    placement,
    tags,
    useTagParser: strategy.use_tag_parser === true,
  }
}

export const getScriptSegmentTypeLabel = (
  segment: Pick<ScriptSegment, 'type'>,
  t?: TranslateFn,
): string => {
  const type = normalizeText(segment.type)
  return type === 'dialogue'
    ? (t ? t('audiobook.scriptQualityReviewDialog.dialogueType') : '对白')
    : type || (t ? t('audiobook.editorSession.speakerFallback') : '旁白')
}

export const getScriptSegmentSpeakerLabel = (
  segment: Pick<ScriptSegment, 'speaker' | 'speaker_name' | 'character_name' | 'role_name'>,
  t?: TranslateFn,
): string =>
  normalizeText(segment.speaker)
  || normalizeText(segment.speaker_name)
  || normalizeText(segment.character_name)
  || normalizeText(segment.role_name)
  || (t ? t('audiobook.editorSession.speakerFallback') : '旁白')

export const formatScriptSegmentSummary = (
  segment: Pick<
    ScriptSegment,
    'type' | 'speaker' | 'speaker_name' | 'character_name' | 'role_name' | 'emotion'
  >,
  index: number,
  t?: TranslateFn,
): string => {
  const emotion = normalizeText(segment.emotion)
  return `#${index + 1} [${getScriptSegmentTypeLabel(segment, t)}] ${getScriptSegmentSpeakerLabel(segment, t)}${
    emotion ? (t ? t('audiobook.segmentLabel.emotionSuffix', { emotion }) : ` · 情绪: ${emotion}`) : ''
  }`
}

export const getSoundEffectsInputValue = (
  segment: Pick<ScriptSegment, 'sound_effects_simple' | 'sound_effects'>,
): string => {
  const simple = Array.isArray(segment.sound_effects_simple)
    ? segment.sound_effects_simple.map(normalizeText).filter(Boolean)
    : []
  if (simple.length > 0) {
    return simple.join(',')
  }

  return Array.isArray(segment.sound_effects)
    ? segment.sound_effects
        .map((item) =>
          typeof item === 'string'
            ? item
            : item?.name || item?.asset_id || item?.effect_id || item?.id || '',
        )
        .map(normalizeText)
        .filter(Boolean)
        .join(',')
    : ''
}

export const getMusicCueInputValue = (
  segment: Pick<ScriptSegment, 'music_cue_simple' | 'music_cue'>,
): string =>
  normalizeText(segment.music_cue_simple)
  || (typeof segment.music_cue === 'string'
    ? normalizeText(segment.music_cue)
    : normalizeText(segment.music_cue?.style) || normalizeText(segment.music_cue?.name))

export const hasPreviewableSoundEffects = (
  segment: Pick<ScriptSegment, 'sound_effects_simple' | 'sound_effects'>,
): boolean => getSoundEffectsInputValue(segment).length > 0

export const hasPreviewableMusicCue = (
  segment: Pick<ScriptSegment, 'music_cue_simple' | 'music_cue'>,
): boolean => getMusicCueInputValue(segment).length > 0
