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
      'onRegenerate(index, segment, option.type)',
      '<Menu',
    ]) {
      expect(actionsSource).toContain(marker)
    }
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
