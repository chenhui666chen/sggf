import { describe, expect, it } from 'vitest'

import {
  createRecordedCloneAudioFile,
  extractCosyVoiceCloneSampleUrl,
} from '../cosyVoiceCloneUploadUtils'

describe('cosyVoiceCloneUploadUtils', () => {
  it('extracts the temporary clone sample url from upload response data', () => {
    expect(extractCosyVoiceCloneSampleUrl({ url: 'oss://sample.wav' })).toBe('oss://sample.wav')
  })

  it('rejects missing or invalid clone sample urls', () => {
    expect(() => extractCosyVoiceCloneSampleUrl(null)).toThrow('未返回临时URL')
    expect(() => extractCosyVoiceCloneSampleUrl({ url: '' })).toThrow('未返回临时URL')
    expect(() => extractCosyVoiceCloneSampleUrl({ url: 123 })).toThrow('未返回临时URL')
  })

  it('creates recorded clone audio files with stable names and fallback mime type', () => {
    const file = createRecordedCloneAudioFile(new Blob(['voice']), 123456)

    expect(file.name).toBe('recording_123456.webm')
    expect(file.type).toBe('audio/webm')
  })

  it('preserves the recorded blob mime type when present', () => {
    const file = createRecordedCloneAudioFile(new Blob(['voice'], { type: 'audio/wav' }), 123456)

    expect(file.type).toBe('audio/wav')
  })
})
