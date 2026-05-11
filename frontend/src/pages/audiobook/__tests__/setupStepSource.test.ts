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
    expect(voiceCatalogStatusPanelSource).toContain('<CosyVoiceVoiceWorkbench {...cosyVoiceWorkbench} />')
    expect(voiceCatalogStatusPanelSource).not.toContain('cloneName: string')
    expect(voiceCatalogStatusPanelSource).not.toContain('onCloneNameChange:')
  })
})
