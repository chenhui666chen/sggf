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
    expect(voiceCatalogStatusPanelSource).toContain('audio.voice 必须传入 data:{MIME_TYPE};base64,$BASE64_AUDIO')
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
})
