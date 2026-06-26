import { describe, expect, it } from 'vitest'

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const readSource = (relativePath: string) =>
  readFileSync(resolve(process.cwd(), relativePath), 'utf-8')

describe('StepAudio voice asset source wiring', () => {
  it('wires the StepAudio clone workbench into the catalog panel', () => {
    const source = readSource('src/pages/audiobook/VoiceCatalogStatusPanel.tsx')

    expect(source).toContain('StepAudioVoiceCloneWorkbench')
    expect(source).toContain("ttsModel === 'stepaudio-2.5-tts'")
    expect(source).toContain('STEPAUDIO_VOICE_CLONE_NOTICE')
  })

  it('exposes StepAudio clone asset API methods', () => {
    const source = readSource('src/services/api.ts')

    expect(source).toContain('previewStepAudioVoiceCloneAssetFromFile')
    expect(source).toContain('/api/v1/audiobook/tts/voices/stepaudio/clone-assets/preview')
    expect(source).toContain('createStepAudioVoiceCloneAssetFromFile')
    expect(source).toContain('/api/v1/audiobook/tts/voices/stepaudio/clone-assets/upload')
    expect(source).toContain('deleteStepAudioVoiceAsset')
  })

  it('sends StepAudio asset ids in custom voice preview payloads', () => {
    const source = readSource('src/pages/audiobook/useAudiobookVoiceActions.ts')

    expect(source).toContain("model === 'stepaudio-2.5-tts'")
    expect(source).toContain('stepaudio_voice_asset_id')
  })

  it('guards StepAudio reference assets that are missing file ids from preview selection', () => {
    const typesSource = readSource('src/pages/audiobook/types.ts')
    const selectSource = readSource('src/pages/audiobook/CharacterVoicePresetSelect.tsx')
    const workbenchSource = readSource('src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx')

    expect(typesSource).toContain('disabled?: boolean')
    expect(typesSource).toContain('disabledReason?: string')
    expect(selectSource).toContain('disabled={Boolean(preset.disabled)}')
    expect(selectSource).toContain('preset.disabledReason')
    expect(workbenchSource).toContain('const presetDisabled = Boolean(preset.disabled)')
    expect(workbenchSource).toContain('disabled={presetDisabled || Boolean(previewingVoiceId) || isDeleting}')
  })

  it('explains that StepAudio file ids can be generated automatically from uploaded samples', () => {
    const workbenchSource = readSource('src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx')

    expect(workbenchSource).toContain('留空自动上传生成')
    expect(workbenchSource).toContain('STEP_API_KEY')
  })

  it('requires StepAudio clone sample text to match the uploaded reference audio', () => {
    const workbenchSource = readSource('src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx')

    expect(workbenchSource).toContain("useState('')")
    expect(workbenchSource).toContain('参考音频逐字内容')
    expect(workbenchSource).toContain('sampleText.trim()')
    expect(workbenchSource).toContain('官方会校验样本文本与音频 ASR')
  })

  it('uses strict transcript recording guidance for StepAudio clone recording', () => {
    const dialogSource = readSource('src/pages/audiobook/CosyVoiceCloneRecordDialog.tsx')
    const workbenchSource = readSource('src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx')

    expect(dialogSource).toContain('strictTranscriptMode')
    expect(dialogSource).toContain('必须逐字朗读下方内容')
    expect(dialogSource).toContain('不要随机朗读其他内容')
    expect(workbenchSource).toContain('strictTranscriptMode')
    expect(workbenchSource).toContain('transcriptText={sampleText.trim()}')
    expect(workbenchSource).toContain('请先填写参考音频逐字内容，再开始录音')
  })

  it('uses a preview-before-confirm flow for billable StepAudio clone voices', () => {
    const workbenchSource = readSource('src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx')

    expect(workbenchSource).toContain('previewStepAudioVoiceCloneAssetFromFile')
    expect(workbenchSource).toContain('previewResult')
    expect(workbenchSource).toContain('handlePreviewClone')
    expect(workbenchSource).toContain('handleConfirmSave')
    expect(workbenchSource).toContain('预试听')
    expect(workbenchSource).toContain('确认保存')
    expect(workbenchSource).toContain('9.9')
  })

  it('requires a second billing confirmation before saving paid StepAudio clone voices', () => {
    const workbenchSource = readSource('src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx')

    expect(workbenchSource).toContain('billingConfirmOpen')
    expect(workbenchSource).toContain('handleRequestConfirmSave')
    expect(workbenchSource).toContain('handleCloseBillingConfirm')
    expect(workbenchSource).toContain('handleConfirmBillingSave')
    expect(workbenchSource).toContain('onClick={handleRequestConfirmSave}')
    expect(workbenchSource).toContain('onClick={handleConfirmBillingSave}')
    expect(workbenchSource).toContain('收费确认')
    expect(workbenchSource).toContain('本次确认保存可能产生 9.9 元/音色费用')
    expect(workbenchSource).toContain('确认收费并保存')
  })
})
