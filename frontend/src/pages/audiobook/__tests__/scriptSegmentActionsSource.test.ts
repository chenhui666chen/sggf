import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const actionsSource = readFileSync(
  new URL('../ScriptSegmentActions.tsx', import.meta.url),
  'utf8',
)

describe('ScriptSegmentActions regeneration candidate controls', () => {
  it('exposes apply and discard actions for pending regeneration candidates', () => {
    for (const marker of [
      'pendingRegeneration',
      'onApplyRegeneration',
      'onDiscardRegeneration',
      'handlePreview',
      'variant="contained"',
      'color="success"',
    ]) {
      expect(actionsSource).toContain(marker)
    }
  })

  it('lets preview and regeneration choose isolated tracks or fused mix', () => {
    for (const marker of [
      'previewOptions',
      'regenerateOptions',
      "type: 'voice'",
      "type: 'sfx'",
      "type: 'bgm'",
      "type: 'mix'",
      'onPreviewAudio(index, segment, option.type)',
      'onRegenerate(index, segment, option.type, option.sourceMode)',
      '<Menu',
    ]) {
      expect(actionsSource).toContain(marker)
    }
  })

  it('splits sfx/bgm regeneration into library matching and AI generation entries', () => {
    for (const marker of [
      '音效重新生成（从库匹配）',
      '音效 AI 重新生成',
      '配乐重新生成（从库匹配）',
      '配乐 AI 重新生成',
      "sourceMode: 'library'",
      "sourceMode: 'ai_generate'",
    ]) {
      expect(actionsSource).toContain(marker)
    }
    expect(actionsSource.match(/sourceMode: 'ai_generate'/g)?.length).toBe(2)
    expect(actionsSource.match(/sourceMode: 'library'/g)?.length).toBe(2)
  })

  it('adds a manual dubbing action next to regeneration controls', () => {
    for (const marker of [
      'MicIcon',
      'StopCircleIcon',
      'voiceRecording',
      'onStartVoiceRecording(index, segment)',
      'onStopVoiceRecording()',
      'handleVoiceRecordingClick',
    ]) {
      expect(actionsSource).toContain(marker)
    }
    expect(actionsSource.indexOf('handleOpenRegenerateMenu')).toBeLessThan(
      actionsSource.indexOf('handleVoiceRecordingClick'),
    )
  })
})
