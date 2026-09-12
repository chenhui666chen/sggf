import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(fileURLToPath(new URL('../AssetStudioWorkbench.tsx', import.meta.url)), 'utf8')

describe('Asset Studio Seed Audio controls', () => {
  it('exposes scene audio generation and speaker references', () => {
    expect(source).toContain("'scene-audio'")
    expect(source).toContain('seed-audio-1.0')
    expect(source).toContain("formData.append('speaker_ids'")
    expect(source).toContain("t('assetStudio.workbench.label.sceneAudioPrompt')")
    expect(source).toContain("t('assetStudio.workbench.label.speakerId')")
  })

  it('does not expose or submit pitch for fixed-voice speech generation', () => {
    expect(source).not.toContain('audioPitch')
    expect(source).not.toContain("formData.append('pitch'")
    expect(source).not.toContain('label="音调"')
  })

  it('only exposes and submits numeric speech rate for basic speed models', () => {
    expect(source).toContain("import { modelUsesBasicNumericSpeedControl } from '@/pages/audiobook/ttsModels'")
    expect(source).toContain('const showAudioNumericSpeedControl =')
    expect(source).toContain('modelUsesBasicNumericSpeedControl(audioModelId)')
    expect(source).toContain('if (showAudioNumericSpeedControl) {')
    expect(source).toContain("formData.append('rate', audioRate)")
    expect(source).toContain('{showAudioNumericSpeedControl ? (')
  })
})
