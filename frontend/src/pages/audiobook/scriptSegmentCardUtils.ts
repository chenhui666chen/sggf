import type {
  AudioAssetSelection,
  InlineTagStrategySummary,
  ScriptSegment,
  ScriptSegmentVoiceParams,
} from './types'

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

export const getScriptSegmentVoiceParams = (
  segment: Pick<ScriptSegment, 'voice_params'>,
): ScriptSegmentVoiceParams =>
  segment.voice_params && typeof segment.voice_params === 'object' ? segment.voice_params : {}

const normalizeText = (value: unknown): string => (typeof value === 'string' ? value.trim() : '')

export const buildSoundEffectAssetPatch = (
  selection: AudioAssetSelection,
): Pick<ScriptSegment, 'sound_effects' | 'sound_effects_simple'> => ({
  sound_effects: [{
    asset_id: normalizeText(selection.id),
    name: normalizeText(selection.name) || normalizeText(selection.label) || normalizeText(selection.id),
  }],
  sound_effects_simple: [],
})

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
): string => {
  const type = normalizeText(segment.type)
  return type === 'dialogue' ? '对白' : type || '旁白'
}

export const getScriptSegmentSpeakerLabel = (
  segment: Pick<ScriptSegment, 'speaker' | 'speaker_name' | 'character_name' | 'role_name'>,
): string =>
  normalizeText(segment.speaker)
  || normalizeText(segment.speaker_name)
  || normalizeText(segment.character_name)
  || normalizeText(segment.role_name)
  || '旁白'

export const formatScriptSegmentSummary = (
  segment: Pick<
    ScriptSegment,
    'type' | 'speaker' | 'speaker_name' | 'character_name' | 'role_name' | 'emotion'
  >,
  index: number,
): string => {
  const emotion = normalizeText(segment.emotion)
  return `#${index + 1} [${getScriptSegmentTypeLabel(segment)}] ${getScriptSegmentSpeakerLabel(segment)}${
    emotion ? ` · 情绪: ${emotion}` : ''
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
