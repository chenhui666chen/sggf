import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

describe('prompt audio review summary source contract', () => {
  it('wires project-level summary and CSV export to the completion step', () => {
    const apiSource = readSource('../../../services/api.ts')
    const completionSource = readSource('../AudiobookCompletionStep.tsx')
    const summaryPanelSource = readSource('../PromptAudioReviewSummaryPanel.tsx')

    expect(apiSource).toContain('getPromptAudioReviewSummary')
    expect(apiSource).toContain('/api/v1/audiobook/projects/${audiobookProjectId}/prompt-audio-review-summary')
    expect(apiSource).toContain('downloadPromptAudioReviewSummaryCsv')
    expect(apiSource).toContain('/api/v1/audiobook/projects/${audiobookProjectId}/prompt-audio-review-summary.csv')
    expect(completionSource).toContain('PromptAudioReviewSummaryPanel')
    expect(summaryPanelSource).toContain('apiClient.getPromptAudioReviewSummary')
    expect(summaryPanelSource).toContain('apiClient.downloadPromptAudioReviewSummaryCsv')
    expect(summaryPanelSource).toContain('triggerBlobDownload')
    expect(summaryPanelSource).toContain('tag_parse_success_rate')
    expect(summaryPanelSource).toContain('text_contamination_rate')
    expect(summaryPanelSource).toContain('average_score')
    expect(summaryPanelSource).toContain('asr_assist_count')
    expect(summaryPanelSource).toContain('asr_tag_residue_count')
  })
})
