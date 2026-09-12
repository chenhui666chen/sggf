import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const workbenchUrl = new URL('../MiniMaxVoiceCloneWorkbench.tsx', import.meta.url)
const workbenchExists = existsSync(workbenchUrl)
const workbenchSource = workbenchExists ? readFileSync(workbenchUrl, 'utf8') : ''
const panelSource = readFileSync(new URL('../VoiceCatalogStatusPanel.tsx', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../../../services/api.ts', import.meta.url), 'utf8')

describe('MiniMax voice clone workbench source guards', () => {
  it('mounts the workbench for both MiniMax Speech 2.8 models', () => {
    expect(workbenchExists).toBe(true)
    expect(panelSource).toContain("ttsModel === 'minimax-speech-2.8-hd'")
    expect(panelSource).toContain("ttsModel === 'minimax-speech-2.8-turbo'")
    expect(panelSource).toContain('<MiniMaxVoiceCloneWorkbench')
  })

  it('confirms supplier charges before creating a clone', () => {
    expect(workbenchSource).toContain('audiobook.minimaxVoiceClone.billingConfirmTitle')
    expect(workbenchSource).toContain('audiobook.minimaxVoiceClone.previewPriceHd')
    expect(workbenchSource).toContain('audiobook.minimaxVoiceClone.billingConfirmUnlock')
    expect(workbenchSource).toContain('audiobook.minimaxVoiceClone.confirmBillingCreate')
  })

  it('uses the MiniMax upload API and can play the returned preview', () => {
    expect(apiSource).toContain('createMiniMaxVoiceCloneFromFile')
    expect(apiSource).toContain('/api/v1/audiobook/tts/voices/minimax/clones/upload')
    expect(workbenchSource).toContain('preview_audio_data_base64')
    expect(workbenchSource).toContain('<audio controls')
  })
})
