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
const chapterScriptResultsSource = readFileSync(
  new URL('../ChapterScriptResults.tsx', import.meta.url),
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

  it('routes script completion review entries to the scene editor for seed_scene batches', () => {
    // GUIDE §2.5：完成步骤的审阅入口必须按引擎分流，
    // seed_scene 章节禁止落入 legacy 单片段工作台
    expect(scriptCompletionSource).toContain('onOpenSceneEditor')
    expect(scriptCompletionSource).toContain('isSeedScene && onOpenSceneEditor')
    expect(scriptCompletionSource).toContain('onOpenSceneEditor={onOpenSceneEditor}')
    expect(chapterScriptResultsSource).toContain("audioEngineMode === 'seed_scene'")
    expect(chapterScriptResultsSource).toContain('onOpenSceneEditor')
    expect(completionStepSource).toContain('onOpenSceneEditor={onOpenSceneEditor}')
    expect(audiobookPageSource).toContain('onOpenSceneEditor={handleOpenCompletionSceneChapter}')
    expect(audiobookPageSource).toContain('const handleOpenCompletionSceneChapter')
    expect(audiobookPageSource).toContain('setSceneEditorTarget')
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
    // 编辑器不直接调用生成 API；生成编排由页面层回调承担
    expect(scriptEditorSource).not.toContain('generateAudioFromScripts')
    expect(scriptEditorActionsSource).not.toContain('generateAudioFromScripts')
    expect(scriptEditorActionsSource).toContain('await refreshAudiobookProjectDetail(audiobookProject.id)')
    expect(audiobookPageSource).toContain('scriptEditorData,\n    refreshAudiobookProjectDetail,')
  })

  it('offers an approve-and-generate shortcut wired at page level', () => {
    // 批准→生成音频链路缩短：编辑台内置组合按钮，编排在 AudiobookPage
    expect(scriptEditorSource).toContain('批准并生成音频')
    expect(scriptEditorSource).toContain('onApproveAndGenerateAudio')
    expect(audiobookPageSource).toContain('onApproveAndGenerateAudio={handleApproveAndGenerateAudio}')
    expect(audiobookPageSource).toContain("handleSaveScript({ nextStatus: 'approved' })")
  })
})
