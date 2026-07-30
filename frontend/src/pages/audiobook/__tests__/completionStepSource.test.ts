import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const completionStepSource = readFileSync(
  new URL('../AudiobookCompletionStep.tsx', import.meta.url),
  'utf8',
)
const scriptCompletionSource = readFileSync(
  new URL('../AudiobookScriptCompletionStep.tsx', import.meta.url),
  'utf8',
)
const workflowStatusSource = readFileSync(
  new URL('../AudiobookWorkflowStatus.tsx', import.meta.url),
  'utf8',
)
const audiobookPageSource = readFileSync(
  new URL('../../AudiobookPage.tsx', import.meta.url),
  'utf8',
)
const scriptEditorSource = readFileSync(
  new URL('../ScriptEditorDialog.tsx', import.meta.url),
  'utf8',
)
const scriptEditorActionsSource = readFileSync(
  new URL('../useAudiobookScriptEditorActions.ts', import.meta.url),
  'utf8',
)

describe('audiobook completion stage boundaries', () => {
  it('routes script-only completion into a dedicated review view', () => {
    expect(completionStepSource).toContain("if (completionMode === 'script_only')")
    expect(completionStepSource).toContain('<AudiobookScriptCompletionStep')
    expect(scriptCompletionSource).toContain('场景剧本已生成')
    expect(scriptCompletionSource).toContain('审阅并批准')
    expect(scriptCompletionSource).toContain('生成场景音频')
  })

  it('keeps audio-only controls outside the script completion component', () => {
    expect(scriptCompletionSource).not.toContain('PromptAudioReviewSummaryPanel')
    expect(scriptCompletionSource).not.toContain('ProjectExportActions')
    expect(scriptCompletionSource).not.toContain('ChapterAudioResults')
    expect(scriptCompletionSource).not.toContain('onOpenBrowserPlayer')
    expect(scriptCompletionSource).not.toContain('onDownloadAudio')
    expect(scriptCompletionSource).not.toContain('onCollectChapterAudio')
  })

  it('names the two workflow stages according to the selected scene engine', () => {
    expect(workflowStatusSource).toContain('生成场景剧本')
    expect(workflowStatusSource).toContain('生成场景音频')
    expect(workflowStatusSource).toContain('lastGenerationMode')
    expect(workflowStatusSource).toContain('audioEngineMode')
    expect(audiobookPageSource).toContain('lastGenerationMode={lastGenerationMode}')
    expect(audiobookPageSource).toContain('audioEngineMode={audioEngineMode}')
  })

  it('approves scripts without bypassing the dedicated scene-audio action', () => {
    expect(scriptEditorSource).toContain("onSaveScript({ nextStatus: 'approved' })")
    expect(scriptEditorSource).toContain('批准剧本')
    expect(scriptEditorSource).not.toContain('generateAudio')
    expect(scriptEditorActionsSource).not.toContain('generateAudioFromScripts')
    expect(scriptEditorActionsSource).toContain('await refreshAudiobookProjectDetail(audiobookProject.id)')
    expect(audiobookPageSource).toContain('scriptEditorData,\n    refreshAudiobookProjectDetail,')
  })
})
