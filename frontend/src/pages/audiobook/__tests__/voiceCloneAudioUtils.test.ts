import { describe, expect, it } from 'vitest'

import {
  createRecordedCloneAudioFile,
  encodePcm16Wav,
  isMimoCloneSupportedAudioFile,
  readAudioFileAsDataUrl,
  summarizeAudioFile,
} from '../voiceCloneAudioUtils'

describe('voiceCloneAudioUtils', () => {
  it('creates a stable audio file from recorded clone blobs', () => {
    const blob = new Blob(['voice'], { type: 'audio/webm' })

    const file = createRecordedCloneAudioFile(blob, 1713657600000)

    expect(file.name).toBe('recording_1713657600000.webm')
    expect(file.type).toBe('audio/webm')
    expect(file.size).toBe(blob.size)
  })

  it('converts uploaded audio files to MiMo-compatible data URLs', async () => {
    const file = new File(['abc'], 'sample.wav', { type: 'audio/wav' })

    await expect(readAudioFileAsDataUrl(file)).resolves.toBe('data:audio/wav;base64,YWJj')
  })

  it('rejects non-audio files before building an audio.voice data URL', async () => {
    const file = new File(['abc'], 'sample.txt', { type: 'text/plain' })

    await expect(readAudioFileAsDataUrl(file)).rejects.toThrow('请选择音频文件')
  })

  it('summarizes MiMo clone samples without exposing base64 payloads', () => {
    const file = new File(['0123456789'], 'sample.wav', { type: 'audio/wav' })

    expect(summarizeAudioFile(file)).toBe('sample.wav · audio/wav · 10 B')
  })

  it('only accepts mp3 and wav files for MiMo Voice Clone samples', () => {
    expect(isMimoCloneSupportedAudioFile(new File(['wav'], 'sample.wav', { type: 'audio/wav' }))).toBe(true)
    expect(isMimoCloneSupportedAudioFile(new File(['mp3'], 'sample.mp3', { type: 'audio/mpeg' }))).toBe(true)
    expect(isMimoCloneSupportedAudioFile(new File(['mp3'], 'sample.mp3', { type: 'audio/mp3' }))).toBe(true)
    expect(isMimoCloneSupportedAudioFile(new File(['wav'], 'sample.wav', { type: '' }))).toBe(true)
    expect(isMimoCloneSupportedAudioFile(new File(['m4a'], 'sample.m4a', { type: 'audio/x-m4a' }))).toBe(false)
    expect(isMimoCloneSupportedAudioFile(new File(['webm'], 'sample.webm', { type: 'audio/webm' }))).toBe(false)
  })

  it('encodes recorded samples as mono PCM wav blobs for MiMo Voice Clone', async () => {
    const wavBlob = encodePcm16Wav(new Float32Array([0, 1, -1]), 24000)

    const bytes = new Uint8Array(await wavBlob.arrayBuffer())
    const text = (start: number, end: number) => String.fromCharCode(...bytes.slice(start, end))

    expect(wavBlob.type).toBe('audio/wav')
    expect(text(0, 4)).toBe('RIFF')
    expect(text(8, 12)).toBe('WAVE')
    expect(text(12, 16)).toBe('fmt ')
    expect(text(36, 40)).toBe('data')
    expect(bytes[20]).toBe(1)
    expect(bytes[22]).toBe(1)
  })
})
