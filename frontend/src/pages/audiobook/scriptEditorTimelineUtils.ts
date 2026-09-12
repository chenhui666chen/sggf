import type { ScriptSegment, TimelineClipEdit, TimelineClipEditMap } from './types'
import type { TranslateFn } from './audioLibraryDisplay'
import {
  getMusicCueInputValue,
  getSoundEffectsInputValue,
  parseCommaSeparatedList,
} from './scriptSegmentCardUtils'

export type TimelineTrackKey = 'scriptVoice' | 'sfx' | 'music'

export interface TimelineTick {
  key: string
  label: string
  segmentIndex: number
  startUnit: number
}

export interface TimelineClip {
  key: string
  track: TimelineTrackKey
  segmentIndex: number
  endSegmentIndex: number
  label: string
  startUnit: number
  durationUnits: number
  textPreview: string
  enabled: boolean
  volume?: number
  speakerLabel?: string
  emotionLabel?: string
}

export type TimelineClipEditOperation = 'move' | 'resize-start' | 'resize-end'

export interface TimelineClipEditAdjustment {
  operation: TimelineClipEditOperation
  deltaUnits: number
  totalUnits: number
  minDurationUnits?: number
}

export interface TimelineModel {
  clipsByTrack: Record<TimelineTrackKey, TimelineClip[]>
  ticks: TimelineTick[]
  segmentOffsets: number[]
  segmentWidths: number[]
  totalUnits: number
}

const MIN_SEGMENT_WIDTH = 64
const MAX_SEGMENT_WIDTH = 220
const EMPTY_SEGMENT_WIDTH = 72
const SEGMENT_TEXT_FACTOR = 1.8
const SEGMENT_WIDTH_PADDING = 56
export const TIMELINE_MIN_EDIT_DURATION_UNITS = 16

const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value))

const normalizeCue = (value: string): string => value.trim().replace(/\s+/g, ' ')

const getSegmentText = (segment: ScriptSegment): string =>
  String(segment.text || '').trim()

const getSegmentWidth = (segment: ScriptSegment): number => {
  const textLength = getSegmentText(segment).length
  if (textLength <= 0) {
    return EMPTY_SEGMENT_WIDTH
  }
  return Math.round(clamp(
    textLength * SEGMENT_TEXT_FACTOR + SEGMENT_WIDTH_PADDING,
    MIN_SEGMENT_WIDTH,
    MAX_SEGMENT_WIDTH,
  ))
}

const buildSegmentLayout = (segments: ScriptSegment[]) => {
  const segmentWidths = segments.map(getSegmentWidth)
  const segmentOffsets: number[] = []
  let totalUnits = 0

  for (const width of segmentWidths) {
    segmentOffsets.push(totalUnits)
    totalUnits += width
  }

  return {
    segmentOffsets,
    segmentWidths,
    totalUnits,
  }
}

const getTimelineTicks = (
  segmentOffsets: number[],
  segmentCount: number,
): TimelineTick[] => {
  if (segmentCount <= 0) return []

  const step = segmentCount > 16 ? 4 : segmentCount > 8 ? 2 : 1
  return Array.from({ length: segmentCount }, (_, segmentIndex) => segmentIndex)
    .filter((segmentIndex) =>
      segmentIndex === 0
      || segmentIndex === segmentCount - 1
      || segmentIndex % step === 0,
    )
    .map((segmentIndex) => ({
      key: `tick-${segmentIndex}`,
      label: `#${segmentIndex + 1}`,
      segmentIndex,
      startUnit: segmentOffsets[segmentIndex] ?? 0,
    }))
}

const createScriptVoiceClip = (
  segment: ScriptSegment,
  segmentIndex: number,
  startUnit: number,
  durationUnits: number,
  t?: TranslateFn,
): TimelineClip => {
  const text = getSegmentText(segment)
  const preview = text.length > 50 ? `${text.slice(0, 50)}...` : text
  const speaker = String(
    segment.voice_params?.speaker
    || segment.speaker
    || segment.speaker_name
    || segment.character_name
    || segment.role_name
    || (t ? t('audiobook.editorSession.speakerFallback') : '旁白'),
  ).trim()
  const emotion = String(segment.emotion || segment.voice_params?.emotion || '').trim()
  const performanceNote = String(segment.performance_notes || '').trim()
  const voicePreview = [
    preview || (t ? t('audiobook.segmentLabel.emptySegment') : '空片段'),
    emotion ? (t ? t('audiobook.segmentLabel.emotion', { emotion }) : `情绪: ${emotion}`) : '',
    performanceNote ? (t ? t('audiobook.segmentLabel.performance', { performance: performanceNote }) : `表演: ${performanceNote}`) : '',
  ].filter(Boolean).join('\n')

  return {
    key: `script-voice-${segmentIndex}`,
    track: 'scriptVoice',
    segmentIndex,
    endSegmentIndex: segmentIndex,
    label: `#${segmentIndex + 1} ${speaker || (t ? t('audiobook.editorSession.speakerFallback') : '旁白')}`,
    startUnit,
    durationUnits,
    textPreview: voicePreview,
    enabled: text.length > 0,
    speakerLabel: speaker || (t ? t('audiobook.editorSession.speakerFallback') : '旁白'),
    emotionLabel: emotion || (t ? t('audiobook.scriptEditor.emotionUnmarked') : '未标注'),
  }
}

const buildSoundEffectClips = (
  segment: ScriptSegment,
  segmentIndex: number,
  startUnit: number,
  durationUnits: number,
): TimelineClip[] => {
  const cues = parseCommaSeparatedList(getSoundEffectsInputValue(segment))
    .map(normalizeCue)
    .filter(Boolean)
  if (cues.length <= 0) return []

  const clipDuration = Math.max(28, Math.min(120, Math.floor(durationUnits * 0.58)))
  const availableOffset = Math.max(0, durationUnits - clipDuration)
  const offsetStep = cues.length > 1 ? availableOffset / (cues.length - 1) : 0

  return cues.map((cue, cueIndex) => ({
    key: `sfx-${segmentIndex}-${cueIndex}`,
    track: 'sfx',
    segmentIndex,
    endSegmentIndex: segmentIndex,
    label: cue,
    startUnit: startUnit + Math.round(offsetStep * cueIndex),
    durationUnits: clipDuration,
    textPreview: cue,
    enabled: true,
  }))
}

const buildMusicClips = (
  segments: ScriptSegment[],
  segmentOffsets: number[],
  segmentWidths: number[],
  t?: TranslateFn,
): TimelineClip[] => {
  const clips: TimelineClip[] = []
  let pendingCue = ''
  let pendingStartIndex = 0

  const closePendingClip = (endSegmentIndex: number) => {
    if (!pendingCue) return

    const startUnit = segmentOffsets[pendingStartIndex] ?? 0
    const endUnit =
      (segmentOffsets[endSegmentIndex] ?? startUnit)
      + (segmentWidths[endSegmentIndex] ?? 0)

    clips.push({
      key: `music-${pendingStartIndex}-${endSegmentIndex}`,
      track: 'music',
      segmentIndex: pendingStartIndex,
      endSegmentIndex,
      label: pendingCue,
      startUnit,
      durationUnits: Math.max(1, endUnit - startUnit),
      textPreview: pendingStartIndex === endSegmentIndex
        ? (t ? t('audiobook.segmentLabel.clip', { index: pendingStartIndex + 1 }) : `片段 #${pendingStartIndex + 1}`)
        : (t ? t('audiobook.segmentLabel.clipRange', { start: pendingStartIndex + 1, end: endSegmentIndex + 1 }) : `片段 #${pendingStartIndex + 1}-#${endSegmentIndex + 1}`),
      enabled: true,
    })
  }

  segments.forEach((segment, segmentIndex) => {
    const cue = normalizeCue(getMusicCueInputValue(segment))
    if (!cue) {
      closePendingClip(segmentIndex - 1)
      pendingCue = ''
      return
    }

    if (!pendingCue) {
      pendingCue = cue
      pendingStartIndex = segmentIndex
      return
    }

    if (cue !== pendingCue) {
      closePendingClip(segmentIndex - 1)
      pendingCue = cue
      pendingStartIndex = segmentIndex
    }
  })

  closePendingClip(segments.length - 1)

  return clips
}

export const buildTimelineModel = (segments: ScriptSegment[], t?: TranslateFn): TimelineModel => {
  const { segmentOffsets, segmentWidths, totalUnits } = buildSegmentLayout(segments)
  const clipsByTrack: Record<TimelineTrackKey, TimelineClip[]> = {
    scriptVoice: [],
    sfx: [],
    music: [],
  }

  segments.forEach((segment, segmentIndex) => {
    const startUnit = segmentOffsets[segmentIndex] ?? 0
    const durationUnits = segmentWidths[segmentIndex] ?? EMPTY_SEGMENT_WIDTH

    clipsByTrack.scriptVoice.push(createScriptVoiceClip(segment, segmentIndex, startUnit, durationUnits, t))
    clipsByTrack.sfx.push(...buildSoundEffectClips(segment, segmentIndex, startUnit, durationUnits))
  })
  clipsByTrack.music = buildMusicClips(segments, segmentOffsets, segmentWidths, t)

  return {
    clipsByTrack,
    ticks: getTimelineTicks(segmentOffsets, segments.length),
    segmentOffsets,
    segmentWidths,
    totalUnits,
  }
}

export const isTimelineClipEditable = (clip: Pick<TimelineClip, 'track'>): boolean =>
  clip.track === 'sfx' || clip.track === 'music'

export const getDefaultTimelineClipVolume = (
  clip: Pick<TimelineClip, 'track'>,
): number => {
  if (clip.track === 'music') return 0.2
  if (clip.track === 'sfx') return 0.5
  return 1
}

export const resolveTimelineSeekSegmentIndex = (
  model: Pick<TimelineModel, 'segmentOffsets' | 'totalUnits'>,
  seekUnit: number,
): number => {
  const segmentCount = model.segmentOffsets.length
  if (segmentCount <= 0) return 0

  const clampedUnit = clamp(Number.isFinite(seekUnit) ? seekUnit : 0, 0, Math.max(0, model.totalUnits))
  for (let index = segmentCount - 1; index >= 0; index -= 1) {
    if (clampedUnit >= (model.segmentOffsets[index] ?? 0)) {
      return index
    }
  }
  return 0
}

export const resolveTimelineSeekSegmentOffsetRatio = (
  model: Pick<TimelineModel, 'segmentOffsets' | 'segmentWidths' | 'totalUnits'>,
  segmentIndex: number,
  seekUnit: number,
): number => {
  const segmentStart = model.segmentOffsets[segmentIndex] ?? 0
  const segmentWidth = model.segmentWidths[segmentIndex] ?? 0
  if (segmentWidth <= 0) return 0

  const clampedUnit = clamp(Number.isFinite(seekUnit) ? seekUnit : 0, 0, Math.max(0, model.totalUnits))
  return clamp((clampedUnit - segmentStart) / segmentWidth, 0, 0.95)
}

export const adjustTimelineClipEdit = (
  edit: TimelineClipEdit,
  adjustment: TimelineClipEditAdjustment,
): TimelineClipEdit => {
  const totalUnits = Math.max(0, adjustment.totalUnits)
  const minDurationUnits = Math.max(1, adjustment.minDurationUnits ?? TIMELINE_MIN_EDIT_DURATION_UNITS)
  const durationUnits = Math.max(minDurationUnits, Math.min(edit.durationUnits, totalUnits || edit.durationUnits))
  const startUnit = clamp(edit.startUnit, 0, Math.max(0, totalUnits - durationUnits))

  if (adjustment.operation === 'move') {
    return {
      startUnit: clamp(startUnit + adjustment.deltaUnits, 0, Math.max(0, totalUnits - durationUnits)),
      durationUnits,
      ...(typeof edit.volume === 'number' ? { volume: edit.volume } : {}),
    }
  }

  if (adjustment.operation === 'resize-start') {
    const clipEnd = startUnit + durationUnits
    const nextStart = clamp(
      startUnit + adjustment.deltaUnits,
      0,
      Math.max(0, clipEnd - minDurationUnits),
    )

    return {
      startUnit: nextStart,
      durationUnits: Math.max(minDurationUnits, clipEnd - nextStart),
      ...(typeof edit.volume === 'number' ? { volume: edit.volume } : {}),
    }
  }

  const maxDuration = Math.max(minDurationUnits, totalUnits - startUnit)
  return {
    startUnit,
    durationUnits: clamp(durationUnits + adjustment.deltaUnits, minDurationUnits, maxDuration),
    ...(typeof edit.volume === 'number' ? { volume: edit.volume } : {}),
  }
}

export const applyTimelineEdits = (
  model: TimelineModel,
  edits: TimelineClipEditMap,
): TimelineModel => ({
  ...model,
  clipsByTrack: {
    scriptVoice: model.clipsByTrack.scriptVoice,
    sfx: model.clipsByTrack.sfx.map((clip) => ({
      ...clip,
      ...(edits[clip.key] || {}),
    })),
    music: model.clipsByTrack.music.map((clip) => ({
      ...clip,
      ...(edits[clip.key] || {}),
    })),
  },
})
