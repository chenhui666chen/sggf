import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

describe('prompt audio manual review source contract', () => {
  it('wires the chapter result prompt/audio review panel to the backend patch API', () => {
    const apiSource = readSource('../../../services/api.ts')
    const chapterAudioItemSource = readSource('../ChapterAudioResultItem.tsx')
    const promptAudioReviewPanelSource = readSource('../PromptAudioManualReviewPanel.tsx')

    expect(apiSource).toContain('updatePromptAudioManualReview')
    expect(apiSource).toContain('queuePromptAudioTranscript')
    expect(apiSource).toContain('/api/v1/audiobook/chapter-audios/${chapterAudioId}/prompt-audio-review')
    expect(apiSource).toContain('/api/v1/audiobook/chapter-audios/${chapterAudioId}/prompt-audio-transcript/queue')
    expect(chapterAudioItemSource).toContain('PromptAudioManualReviewPanel')
    expect(chapterAudioItemSource).toContain('setShowPromptAudioReview(true)')
    expect(promptAudioReviewPanelSource).toContain('getPromptAudioQualitySummary')
    expect(promptAudioReviewPanelSource).toContain('apiClient.updatePromptAudioManualReview')
    expect(promptAudioReviewPanelSource).toContain('apiClient.queuePromptAudioTranscript')
    expect(promptAudioReviewPanelSource).toContain("provider: 'mimo'")
    expect(promptAudioReviewPanelSource).toContain('confirm_cost: true')
    expect(promptAudioReviewPanelSource).toContain('model: currentModel?.model')
    expect(promptAudioReviewPanelSource).toContain('handleQueueTranscript')
    expect(promptAudioReviewPanelSource).toContain('promptAudioReviewModels')
    expect(promptAudioReviewPanelSource).toContain('tag_parse_success: parseReviewBooleanValue')
    expect(promptAudioReviewPanelSource).toContain('text_contamination: parseReviewBooleanValue')
    expect(promptAudioReviewPanelSource).toContain('asr_transcript: asrTranscript || null')
    expect(promptAudioReviewPanelSource).toContain('asrAssist')
    expect(promptAudioReviewPanelSource).toContain('suggestedTextContamination')
    expect(promptAudioReviewPanelSource).toContain('audiobook.promptAudioManualReview.queueTranscript')
  })
})
