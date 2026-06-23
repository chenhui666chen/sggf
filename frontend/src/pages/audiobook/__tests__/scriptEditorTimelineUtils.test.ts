import { describe, expect, it } from 'vitest'

import {
  adjustTimelineClipEdit,
  applyTimelineEdits,
  buildTimelineModel,
  isTimelineClipEditable,
  resolveTimelineSeekSegmentOffsetRatio,
  resolveTimelineSeekSegmentIndex,
} from '../scriptEditorTimelineUtils'
import type { ScriptSegment } from '../types'

const createSegment = (patch: Partial<ScriptSegment> = {}): ScriptSegment => ({
  text: 'Narration text',
  ...patch,
})

describe('scriptEditorTimelineUtils', () => {
  it('builds a professional three-track model with script and voice combined as the primary track', () => {
    const model = buildTimelineModel([
      createSegment({
        text: 'First line.',
        speaker_name: '林晚',
        emotion: '克制',
      }),
      createSegment({ text: 'Second line.', sound_effects_simple: ['door close'] }),
      createSegment({ text: 'Third line.' }),
    ])

    expect(Object.keys(model.clipsByTrack)).toEqual(['scriptVoice', 'sfx', 'music'])
    expect(model.clipsByTrack.scriptVoice).toHaveLength(3)
    expect(model.clipsByTrack.scriptVoice[0]).toMatchObject({
      track: 'scriptVoice',
      segmentIndex: 0,
      label: '#1 林晚',
      speakerLabel: '林晚',
      emotionLabel: '克制',
      enabled: true,
    })
    expect(model.clipsByTrack.sfx).toHaveLength(1)
    expect(model.clipsByTrack.sfx[0]).toMatchObject({
      track: 'sfx',
      segmentIndex: 1,
      label: 'door close',
      enabled: true,
    })
  })

  it('keeps empty script voice clips visible but marks them disabled', () => {
    const model = buildTimelineModel([
      createSegment({ text: '', speaker_name: '旁白' }),
    ])

    expect(model.clipsByTrack.scriptVoice).toHaveLength(1)
    expect(model.clipsByTrack.scriptVoice[0]).toMatchObject({
      track: 'scriptVoice',
      label: '#1 旁白',
      textPreview: '空片段',
      enabled: false,
    })
  })

  it('splits multiple sound effect cues inside one segment into separate timeline clips', () => {
    const model = buildTimelineModel([
      createSegment({ sound_effects_simple: ['wind', 'footstep'] }),
    ])

    expect(model.clipsByTrack.sfx.map((clip) => clip.label)).toEqual(['wind', 'footstep'])
    expect(model.clipsByTrack.sfx[0].startUnit).toBeLessThan(model.clipsByTrack.sfx[1].startUnit)
    expect(model.clipsByTrack.sfx.every((clip) => clip.durationUnits > 0)).toBe(true)
  })

  it('merges continuous equal music cues into one long music clip', () => {
    const model = buildTimelineModel([
      createSegment({ text: 'Calm opening.', music_cue_simple: 'calm pad' }),
      createSegment({ text: 'Calm continues.', music_cue_simple: 'calm pad' }),
      createSegment({ text: 'Silence here.' }),
      createSegment({ text: 'Action starts.', music_cue_simple: 'action pulse' }),
    ])

    expect(model.clipsByTrack.music).toHaveLength(2)
    expect(model.clipsByTrack.music[0]).toMatchObject({
      track: 'music',
      segmentIndex: 0,
      endSegmentIndex: 1,
      label: 'calm pad',
      enabled: true,
    })
    expect(model.clipsByTrack.music[0].durationUnits).toBe(
      model.segmentWidths[0] + model.segmentWidths[1],
    )
    expect(model.clipsByTrack.music[1]).toMatchObject({
      segmentIndex: 3,
      endSegmentIndex: 3,
      label: 'action pulse',
    })
  })

  it('builds shared monotonic segment offsets and timeline ticks for all tracks', () => {
    const model = buildTimelineModel([
      createSegment({ text: 'A short line.' }),
      createSegment({ text: 'A much longer line that should occupy more timeline width.' }),
      createSegment({ text: 'Final line.' }),
    ])

    expect(model.segmentOffsets).toHaveLength(3)
    expect(model.segmentOffsets[0]).toBe(0)
    expect(model.segmentOffsets[1]).toBeGreaterThan(model.segmentOffsets[0])
    expect(model.segmentOffsets[2]).toBeGreaterThan(model.segmentOffsets[1])
    expect(model.totalUnits).toBeGreaterThan(0)
    expect(model.ticks.map((tick) => tick.segmentIndex)).toEqual([0, 1, 2])
  })

  it('resolves a dragged playhead position to the active segment index', () => {
    const model = buildTimelineModel([
      createSegment({ text: 'First line.' }),
      createSegment({ text: 'A much longer second line for timeline width.' }),
      createSegment({ text: 'Final line.' }),
    ])

    expect(resolveTimelineSeekSegmentIndex(model, -20)).toBe(0)
    expect(resolveTimelineSeekSegmentIndex(model, model.segmentOffsets[0])).toBe(0)
    expect(resolveTimelineSeekSegmentIndex(model, model.segmentOffsets[1])).toBe(1)
    expect(resolveTimelineSeekSegmentIndex(model, model.segmentOffsets[2] + 1)).toBe(2)
    expect(resolveTimelineSeekSegmentIndex(model, model.totalUnits + 500)).toBe(2)
  })

  it('resolves a dragged playhead position to a proportional offset inside the segment audio', () => {
    const model = buildTimelineModel([
      createSegment({ text: 'First line.' }),
      createSegment({ text: 'A much longer second line for timeline width.' }),
      createSegment({ text: 'Final line.' }),
    ])
    const segmentIndex = 1
    const segmentStart = model.segmentOffsets[segmentIndex]
    const segmentWidth = model.segmentWidths[segmentIndex]

    expect(resolveTimelineSeekSegmentOffsetRatio(model, segmentIndex, segmentStart - 100)).toBe(0)
    expect(resolveTimelineSeekSegmentOffsetRatio(model, segmentIndex, segmentStart)).toBe(0)
    expect(resolveTimelineSeekSegmentOffsetRatio(model, segmentIndex, segmentStart + segmentWidth / 2)).toBeCloseTo(0.5)
    expect(resolveTimelineSeekSegmentOffsetRatio(model, segmentIndex, segmentStart + segmentWidth + 100)).toBe(0.95)
  })

  it('marks sound effect and music clips editable while keeping the script voice anchor locked', () => {
    const model = buildTimelineModel([
      createSegment({
        sound_effects_simple: ['door close'],
        music_cue_simple: 'calm pad',
      }),
    ])

    expect(isTimelineClipEditable(model.clipsByTrack.scriptVoice[0])).toBe(false)
    expect(isTimelineClipEditable(model.clipsByTrack.sfx[0])).toBe(true)
    expect(isTimelineClipEditable(model.clipsByTrack.music[0])).toBe(true)
  })

  it('moves editable clip edits and clamps them inside the timeline', () => {
    expect(adjustTimelineClipEdit(
      { startUnit: 30, durationUnits: 40 },
      { operation: 'move', deltaUnits: 25, totalUnits: 100 },
    )).toEqual({ startUnit: 55, durationUnits: 40 })

    expect(adjustTimelineClipEdit(
      { startUnit: 80, durationUnits: 30 },
      { operation: 'move', deltaUnits: 30, totalUnits: 100 },
    )).toEqual({ startUnit: 70, durationUnits: 30 })

    expect(adjustTimelineClipEdit(
      { startUnit: 10, durationUnits: 30 },
      { operation: 'move', deltaUnits: -25, totalUnits: 100 },
    )).toEqual({ startUnit: 0, durationUnits: 30 })
  })

  it('resizes editable clip edits from both edges with a minimum duration', () => {
    expect(adjustTimelineClipEdit(
      { startUnit: 30, durationUnits: 40 },
      { operation: 'resize-start', deltaUnits: 10, totalUnits: 100, minDurationUnits: 16 },
    )).toEqual({ startUnit: 40, durationUnits: 30 })

    expect(adjustTimelineClipEdit(
      { startUnit: 30, durationUnits: 40 },
      { operation: 'resize-start', deltaUnits: 50, totalUnits: 100, minDurationUnits: 16 },
    )).toEqual({ startUnit: 54, durationUnits: 16 })

    expect(adjustTimelineClipEdit(
      { startUnit: 30, durationUnits: 40 },
      { operation: 'resize-end', deltaUnits: -50, totalUnits: 100, minDurationUnits: 16 },
    )).toEqual({ startUnit: 30, durationUnits: 16 })
  })

  it('applies clip edit overrides only to matching timeline clips', () => {
    const model = buildTimelineModel([
      createSegment({ sound_effects_simple: ['door close'] }),
    ])
    const editedModel = applyTimelineEdits(model, {
      [model.clipsByTrack.sfx[0].key]: { startUnit: 12, durationUnits: 64 },
    })

    expect(editedModel.clipsByTrack.sfx[0]).toMatchObject({
      startUnit: 12,
      durationUnits: 64,
    })
    expect(editedModel.clipsByTrack.scriptVoice[0]).toEqual(model.clipsByTrack.scriptVoice[0])
  })
})
