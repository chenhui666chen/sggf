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
    expect(previewSource).toContain('candidateId')
    expect(previewSource).toContain('audioPath: savedAudioPath, previewType')
    expect(previewSource).not.toContain('candidateAudioPath')
    expect(previewSource).toContain('resolveSegmentAudioPath')
    expect(previewSource).toContain('pendingSegmentRegenerations[index]?.[previewType]')
    expect(previewSource).not.toContain('apiClient.previewScriptSegmentAudio(')
    // 管线生成的音效/配乐无持久化分轨时，允许仅凭 preview_type 交由服务端时间线渲染
    expect(previewSource).toContain('canPreviewPipelineTimeline')
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
