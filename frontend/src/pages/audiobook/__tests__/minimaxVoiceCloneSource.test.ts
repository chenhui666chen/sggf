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
    expect(workbenchSource).toContain('收费确认')
    expect(workbenchSource).toContain('3.5 元/万字符')
    expect(workbenchSource).toContain('首次用于正式语音合成')
    expect(workbenchSource).toContain('9.9 元')
    expect(workbenchSource).toContain('确认收费并创建')
  })

  it('uses the MiniMax upload API and can play the returned preview', () => {
    expect(apiSource).toContain('createMiniMaxVoiceCloneFromFile')
    expect(apiSource).toContain('/api/v1/audiobook/tts/voices/minimax/clones/upload')
    expect(workbenchSource).toContain('preview_audio_data_base64')
    expect(workbenchSource).toContain('<audio controls')
  })
})
