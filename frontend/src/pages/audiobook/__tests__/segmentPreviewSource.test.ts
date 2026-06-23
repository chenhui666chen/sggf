import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const previewSource = readFileSync(
  new URL('../useAudiobookSegmentPreview.ts', import.meta.url),
  'utf8',
)
const playbackSource = readFileSync(
  new URL('../useAudiobookAudioPlayback.ts', import.meta.url),
  'utf8',
)
const hookTypesSource = readFileSync(
  new URL('../hookTypes.ts', import.meta.url),
  'utf8',
)

describe('useAudiobookSegmentPreview source contract', () => {
  it('plays candidate or committed segment audio without generating a fresh preview', () => {
    expect(previewSource).toContain('pendingRegeneration')
    expect(previewSource).toContain('getSegmentRegenerationCandidateAudio')
    expect(previewSource).toContain('candidateAudioPath')
    expect(previewSource).toContain('resolveSegmentAudioPath')
    expect(previewSource).toContain('pendingSegmentRegenerations[index]?.[previewType]')
    expect(previewSource).not.toContain('apiClient.previewScriptSegmentAudio(')
  })

  it('can start segment preview playback from a timeline seek ratio', () => {
    expect(hookTypesSource).toContain('startRatio?: number')
    expect(previewSource).toContain('options?: SegmentPreviewPlaybackOptions')
    expect(previewSource).toContain('startRatio: options?.startRatio')
    expect(playbackSource).toContain('applyPlaybackStart')
    expect(playbackSource).toContain('audioElement.currentTime =')
  })

  it('falls back to generated chapter audio when no independent segment audio exists', () => {
    expect(previewSource).toContain('chapterAudioAvailable')
    expect(previewSource).toContain('segmentTimings')
    expect(previewSource).toContain('resolveSegmentTimelineStartTime')
    expect(previewSource).toContain('getAudiobookChapterAudioSignedStreamUrl')
    expect(previewSource).toContain('startTime:')
  })
})
