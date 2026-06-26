import { describe, expect, it } from 'vitest'

import { normalizeCosyVoicePreviewAudioUrl } from '../useAudiobookVoiceActions'

describe('voiceActions utils', () => {
  it('normalizes bare CosyVoice preview audio base64 into a playable data URL', () => {
    expect(normalizeCosyVoicePreviewAudioUrl('YWJj')).toBe('data:audio/wav;base64,YWJj')
  })

  it('keeps existing playable preview audio URLs unchanged', () => {
    expect(normalizeCosyVoicePreviewAudioUrl('https://example.com/preview.wav')).toBe(
      'https://example.com/preview.wav',
    )
    expect(normalizeCosyVoicePreviewAudioUrl('data:audio/wav;base64,YWJj')).toBe(
      'data:audio/wav;base64,YWJj',
    )
  })
})
