import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const reviewActionsSource = readFileSync(
  new URL('../useAudiobookSegmentReviewActions.ts', import.meta.url),
  'utf8',
)

describe('useAudiobookSegmentReviewActions source contract', () => {
  it('creates a pending candidate instead of directly overwriting segment audio', () => {
    expect(reviewActionsSource).toContain('segment,')
    expect(reviewActionsSource).toContain('pendingSegmentRegenerations')
    expect(reviewActionsSource).toContain('generateSegmentRegenerationCandidate')
    expect(reviewActionsSource).toContain('applySegmentRegenerationCandidate')
    expect(reviewActionsSource).toContain('handleDiscardSegmentRegenerationCandidate')
    expect(reviewActionsSource).toContain('candidate_audio_path')
    expect(reviewActionsSource).toContain('previewType: PreviewType')
    expect(reviewActionsSource).toContain('preview_type: previewType')
    expect(reviewActionsSource).toContain('previewType: candidateResponse.data?.preview_type')
    expect(reviewActionsSource).not.toContain('const refreshRes = await apiClient.getAudiobookChapterScript')
    expect(reviewActionsSource).not.toContain('apiClient.regenerateSegment(')
  })

  it('records human dubbing as a voice regeneration candidate', () => {
    for (const marker of [
      'MediaRecorder',
      'recordingSegmentIndex',
      'handleStartSegmentVoiceRecording',
      'handleStopSegmentVoiceRecording',
      'uploadSegmentVoiceRecordingCandidate',
      "const voicePreviewType: PreviewType = 'voice'",
      '[voicePreviewType]',
      "candidateResponse.data?.preview_type || 'voice'",
    ]) {
      expect(reviewActionsSource).toContain(marker)
    }
  })
})
