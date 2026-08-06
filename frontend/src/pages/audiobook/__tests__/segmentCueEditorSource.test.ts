import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const cueDialogUrl = new URL('../SegmentCueEditorDialog.tsx', import.meta.url)
const cueDialogSource = existsSync(cueDialogUrl) ? readFileSync(cueDialogUrl, 'utf8') : ''
const editorSource = readFileSync(
  new URL('../ScriptEditorDialog.tsx', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../../../services/api.ts', import.meta.url),
  'utf8',
)

describe('single-segment cue editor', () => {
  it('opens focused voice, sound-effect, and music dialogs from cue panels', () => {
    for (const marker of [
      'SegmentCueEditorDialog',
      'cueEditorType',
      "openCueEditor('voice')",
      "openCueEditor('sfx')",
      "openCueEditor('bgm')",
      'onApplyPatch',
    ]) {
      expect(editorSource).toContain(marker)
    }
  })

  it('supports user reading analysis and model-aware assist with static reading text', () => {
    for (const marker of [
      '要朗读的文本',
      'MediaRecorder',
      'getUserMedia',
      'analyzeSegmentDirectionReading',
      'MAX_READING_RECORDING_SECONDS',
      'assistSegmentDirection',
      'model_capabilities',
      'warnings',
      '智能整理',
      '应用到片段',
      'AudioPicker',
      "formData.append('file'",
    ]) {
      expect(cueDialogSource).toContain(marker)
    }
    // 示范朗读试听与录音转写口述均已下线，弹窗不再调用预览合成与旧转写接口
    expect(cueDialogSource).not.toContain('previewScriptSegmentAudio')
    expect(cueDialogSource).not.toContain('transcribeSegmentDirectionAudio')
    expect(cueDialogSource).not.toContain('示范朗读')
    expect(apiSource).toContain('/direction-assist')
    expect(apiSource).toContain('/direction-audio/analyze')
    expect(apiSource).not.toContain('/direction-audio/transcribe')
    // FormData 上传必须显式声明 multipart，否则 axios 默认 application/json 会导致后端 422
    const analyzeSection = apiSource.slice(apiSource.indexOf('analyzeSegmentDirectionReading'))
    expect(analyzeSection.slice(0, 800)).toContain("'Content-Type': 'multipart/form-data'")
  })

  it('offers structured assist for every cue and preserves selected library assets', () => {
    expect(cueDialogSource).toContain('onClick={() => void handleAssist()}')
    expect(cueDialogSource).not.toContain("cueType === 'voice' && (\n          <Button\n            variant=\"outlined\"")
    expect(cueDialogSource).toContain('mergeAssistPatchWithSelectedAsset')
    expect(cueDialogSource).toContain('sanitizeScriptSegmentVoiceIdentityControls')
    expect(cueDialogSource).toContain('sound_effects')
    expect(cueDialogSource).toContain('music_cue')
  })

  it('allows an asset-only cue and stops reading recording when the dialog closes', () => {
    expect(cueDialogSource).toContain('const canApply = Boolean(description.trim() || selectedAsset || assistResult)')
    expect(cueDialogSource).toContain('disabled={assistLoading || recording || analyzing || !canApply}')
    expect(cueDialogSource).toContain('onClose={handleClose}')
    expect(cueDialogSource).toContain('abortReadingRecording()')
    expect(cueDialogSource).toContain('readingSessionRef.current += 1')
    expect(cueDialogSource).toContain('sessionId !== readingSessionRef.current')
  })
})
