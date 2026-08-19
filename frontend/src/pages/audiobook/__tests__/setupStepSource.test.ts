import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const audiobookPageSource = readFileSync(
  new URL('../../AudiobookPage.tsx', import.meta.url),
  'utf8',
)
const setupStepSource = readFileSync(
  new URL('../AudiobookSetupStep.tsx', import.meta.url),
  'utf8',
)
const voiceCatalogStatusPanelSource = readFileSync(
  new URL('../VoiceCatalogStatusPanel.tsx', import.meta.url),
  'utf8',
)
const mimoVoiceAssetWorkbenchSource = readFileSync(
  new URL('../MimoVoiceAssetWorkbench.tsx', import.meta.url),
  'utf8',
)
const cloneRecordDialogSource = readFileSync(
  new URL('../CosyVoiceCloneRecordDialog.tsx', import.meta.url),
  'utf8',
)
const voiceActionsSource = readFileSync(
  new URL('../useAudiobookVoiceActions.ts', import.meta.url),
  'utf8',
)
const narrationAudioConfigPanelSource = readFileSync(
  new URL('../NarrationAudioConfigPanel.tsx', import.meta.url),
  'utf8',
)
const audioFxConfigPanelSource = readFileSync(
  new URL('../AudioFxConfigPanel.tsx', import.meta.url),
  'utf8',
)
const scriptEditorDialogSource = readFileSync(
  new URL('../ScriptEditorDialog.tsx', import.meta.url),
  'utf8',
)
const chapterSelectionPanelSource = readFileSync(
  new URL('../ChapterSelectionPanel.tsx', import.meta.url),
  'utf8',
)
const chapterActionsMenuSource = readFileSync(
  new URL('../ChapterActionsMenu.tsx', import.meta.url),
  'utf8',
)

describe('Audiobook setup source guards', () => {
  it('keeps CosyVoice workbench fields grouped below the page boundary', () => {
    expect(audiobookPageSource).toContain('const cosyVoiceWorkbench = useCosyVoiceWorkbench({')
    expect(audiobookPageSource).toContain('cosyVoiceWorkbench={cosyVoiceWorkbench}')

    expect(setupStepSource).toContain('cosyVoiceWorkbench: CosyVoiceWorkbench')
    expect(setupStepSource).toContain('cosyVoiceWorkbench={cosyVoiceWorkbench}')
    expect(setupStepSource).not.toContain('cloneName: string')
    expect(setupStepSource).not.toContain('cloneUrl: string')
    expect(setupStepSource).not.toContain('onCloneNameChange:')
    expect(setupStepSource).not.toContain('onCreateDesignVoice:')

    expect(voiceCatalogStatusPanelSource).toContain('cosyVoiceWorkbench: CosyVoiceWorkbench')
    expect(voiceCatalogStatusPanelSource).toContain(
      '<CosyVoiceVoiceWorkbench {...cosyVoiceWorkbench} />',
    )
    expect(voiceCatalogStatusPanelSource).toContain('ttsModel === \'cosyvoice-v3.5-plus\'')
    expect(voiceCatalogStatusPanelSource).toContain('ttsModel === \'mimo-v2.5-tts-voiceclone\'')
    expect(voiceCatalogStatusPanelSource).toContain('上传或录制授权样本并保存为可复用音色')
    expect(voiceCatalogStatusPanelSource).toContain('ttsModel === \'mimo-v2.5-tts-voicedesign\'')
    expect(voiceCatalogStatusPanelSource).toContain('填写 voice design prompt 并保存为可复用音色')
    expect(voiceCatalogStatusPanelSource).toContain('再到角色音色下拉中选用')
    expect(voiceCatalogStatusPanelSource).not.toContain('cloneName: string')
    expect(voiceCatalogStatusPanelSource).not.toContain('onCloneNameChange:')
    expect(mimoVoiceAssetWorkbenchSource).toContain('音色名称')
    expect(mimoVoiceAssetWorkbenchSource).toContain('保存音色')
    expect(mimoVoiceAssetWorkbenchSource).toContain('上传音频')
    expect(mimoVoiceAssetWorkbenchSource).toContain('录音')
    expect(mimoVoiceAssetWorkbenchSource).toContain('VISIBLE_MIMO_VOICE_LIMIT = 3')
    expect(mimoVoiceAssetWorkbenchSource).toContain('visiblePresets')
    expect(mimoVoiceAssetWorkbenchSource).toContain('hiddenPresetCount')
    expect(mimoVoiceAssetWorkbenchSource).toContain('IconButton')
    expect(mimoVoiceAssetWorkbenchSource).toContain('PlayArrowIcon')
    expect(mimoVoiceAssetWorkbenchSource).toContain('DeleteOutlineIcon')
    expect(mimoVoiceAssetWorkbenchSource).toContain('onPreviewCustomVoice')
    expect(mimoVoiceAssetWorkbenchSource).toContain('label="声音描述"')
    expect(mimoVoiceAssetWorkbenchSource).toContain('minRows={3}')
    expect(mimoVoiceAssetWorkbenchSource).toContain('summarizeAudioFile')
    expect(mimoVoiceAssetWorkbenchSource).toContain('isMimoCloneSupportedAudioFile')
    expect(mimoVoiceAssetWorkbenchSource).toContain('convertRecordedAudioBlobToWavFile')
    expect(mimoVoiceAssetWorkbenchSource).toContain('accept=".mp3,.wav,audio/mpeg,audio/wav"')
    expect(mimoVoiceAssetWorkbenchSource).toContain('已选择音频样本')
    expect(mimoVoiceAssetWorkbenchSource).toContain('清除样本')
    expect(mimoVoiceAssetWorkbenchSource).toContain('createMimoVoiceCloneAssetFromFile')
    expect(mimoVoiceAssetWorkbenchSource).not.toContain('readAudioFileAsDataUrl')
    expect(mimoVoiceAssetWorkbenchSource).not.toContain('audio.voice data URL')
    expect(mimoVoiceAssetWorkbenchSource).not.toContain('资产名称')
    expect(mimoVoiceAssetWorkbenchSource).not.toContain('保存资产')
    expect(mimoVoiceAssetWorkbenchSource).not.toContain('备注')
    expect(mimoVoiceAssetWorkbenchSource).not.toContain('setDescription')
    expect(mimoVoiceAssetWorkbenchSource).not.toContain('description,')
  })

  it('closes recording dialogs once recorded audio is handed to the upload flow', () => {
    const mimoUploadStart = mimoVoiceAssetWorkbenchSource.indexOf(
      'const uploadRecordedAudio = async (blob: Blob) => {',
    )
    const mimoUploadEnd = mimoVoiceAssetWorkbenchSource.indexOf(
      'const {',
      mimoUploadStart,
    )
    const mimoUploadBlock = mimoVoiceAssetWorkbenchSource.slice(mimoUploadStart, mimoUploadEnd)

    expect(mimoUploadStart).toBeGreaterThanOrEqual(0)
    expect(mimoUploadBlock).toContain('setRecordDialogOpen(false)')

    const cosyUploadStart = voiceActionsSource.indexOf(
      'const uploadRecordedCloneAudio = useCallback(async (blob: Blob) => {',
    )
    const cosyUploadEnd = voiceActionsSource.indexOf(
      'const {',
      cosyUploadStart,
    )
    const cosyUploadBlock = voiceActionsSource.slice(cosyUploadStart, cosyUploadEnd)

    expect(cosyUploadStart).toBeGreaterThanOrEqual(0)
    expect(cosyUploadBlock).toContain('setCloneRecordDialogOpen(false)')
  })

  it('shows live recording statistics after recording starts', () => {
    expect(cloneRecordDialogSource).toContain('RECORD_TARGET_SECONDS = 10')
    expect(cloneRecordDialogSource).toContain('recordElapsedSeconds')
    expect(cloneRecordDialogSource).toContain('setInterval')
    expect(cloneRecordDialogSource).toContain('录音统计')
    expect(cloneRecordDialogSource).toContain('已录时长')
    expect(cloneRecordDialogSource).toContain('LinearProgress')
  })

  it('keeps setup controls focused on script-first generation and hides narration style and balance toggles', () => {
    expect(setupStepSource).not.toContain('配置章节与角色声音')
    expect(setupStepSource).not.toContain('title="生成策略"')
    expect(setupStepSource).not.toContain('只生成剧本和评审')
    expect(setupStepSource).not.toContain('适合先审稿再进入音频阶段')
    expect(setupStepSource).not.toContain('生成剧本、音频与导出素材')
    expect(setupStepSource).not.toContain('适合一次性完成可试听章节')
    expect(setupStepSource).not.toContain('完整音频链路')
    expect(setupStepSource).not.toContain('onScriptOnlyModeChange')
    expect(setupStepSource).not.toContain('项目默认 TTS 模型')
    expect(setupStepSource).not.toContain('onTtsModelChange=')
    expect(setupStepSource).not.toContain('onTtsModelChange:')
    expect(setupStepSource).not.toContain('onTtsModelChange(event.target.value as TtsModel)')
    expect(setupStepSource).toContain('音色管理')
    expect(setupStepSource).toContain('VoiceCatalogStatusPanel')
    expect(setupStepSource).toContain('Dialog')

    expect(narrationAudioConfigPanelSource).not.toContain('NarrationStyleSelector')
    expect(narrationAudioConfigPanelSource).not.toContain('getNarrationStyles')
    expect(narrationAudioConfigPanelSource).not.toContain('ToggleButtonGroup')
    expect(narrationAudioConfigPanelSource).not.toContain('生成引擎')
    expect(narrationAudioConfigPanelSource).not.toContain('场景生成')
    expect(narrationAudioConfigPanelSource).not.toContain('旁白风格')
    expect(setupStepSource).toContain('生成引擎')
    expect(setupStepSource).toContain('场景生成')
    expect(audioFxConfigPanelSource).not.toContain('智能音量平衡')
    expect(audioFxConfigPanelSource).not.toContain('intelligent_balance')
    expect(audioFxConfigPanelSource).not.toContain('平衡策略')
    expect(audioFxConfigPanelSource).not.toContain('BGM 音量')
    expect(audioFxConfigPanelSource).not.toContain('音效音量')
    expect(scriptEditorDialogSource).toContain('片段音量')
    expect(scriptEditorDialogSource).toContain('选中音频片段音量')
    expect(setupStepSource).toContain('生成本章场景剧本')
  })

  it('uses a single-select locked chapter queue with regeneration actions', () => {
    expect(chapterSelectionPanelSource).toContain('Radio')
    expect(chapterSelectionPanelSource).not.toContain('Checkbox')
    expect(chapterSelectionPanelSource).not.toContain('onToggleAll')
    expect(chapterSelectionPanelSource).toContain('generatedChapterIds')
    expect(chapterSelectionPanelSource).toContain('已生成')
    expect(chapterSelectionPanelSource).toContain('scrollTop')
    // 已生成章节点击整行直接进入该章工作台，而不是无响应
    expect(chapterSelectionPanelSource).toContain('onOpenGeneratedChapter')
    expect(chapterSelectionPanelSource).toContain('已生成 · 点击进入工作台')
    expect(setupStepSource).toContain('onOpenGeneratedChapter={onOpenGeneratedChapter}')
    // §3.1：点击已生成章节按引擎分流（legacy_stems → 剧本编辑器 / seed_scene → 场景编辑器）
    expect(audiobookPageSource).toContain('onOpenGeneratedChapter={handleOpenGeneratedChapter}')
    expect(audiobookPageSource).toContain('handleOpenScriptEditor')
    expect(audiobookPageSource).toContain('SceneChapterEditor')
    expect(chapterActionsMenuSource).toContain('canRegenerate')
    expect(chapterActionsMenuSource).toContain('重新生成')
  })

  it('stacks chapters before narration on the left with voices on the right', () => {
    const narrationIndex = setupStepSource.indexOf('title="叙事与音频"')
    const chapterQueueIndex = setupStepSource.indexOf('title="章节队列"')
    const voiceIndex = setupStepSource.indexOf('title="角色声音"')
    const generateButtonRowIndex = setupStepSource.indexOf('audiobookButtonRowSx.singlePrimary')

    expect(chapterQueueIndex).toBeGreaterThanOrEqual(0)
    expect(narrationIndex).toBeGreaterThan(chapterQueueIndex)
    expect(voiceIndex).toBeGreaterThan(narrationIndex)
    expect(generateButtonRowIndex).toBeGreaterThan(voiceIndex)
    expect(setupStepSource).toContain("lg: 'minmax(360px, 0.92fr) minmax(0, 1.38fr)'")
  })
})
