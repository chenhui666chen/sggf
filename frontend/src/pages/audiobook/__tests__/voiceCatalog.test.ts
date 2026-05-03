import { describe, expect, it } from 'vitest'

import { normalizeVoiceCatalogPayload } from '../voiceCatalog'

describe('audiobook voiceCatalog', () => {
  it('normalizes voice entries and fills catalog metadata defaults', () => {
    const catalog = normalizeVoiceCatalogPayload('qwen3-tts-instruct-flash', {
      model: 'qwen3-tts-instruct-flash',
      updated_at: '2026-04-30',
      source: 'official',
      voices: [
        {
          id: 'Neil',
          speaker: 'Neil',
          label: 'Neil',
          supportsInstruct: 'yes' as unknown as boolean,
        },
      ],
    })

    expect(catalog.voices).toEqual([
      {
        id: 'Neil',
        speaker: 'Neil',
        label: 'Neil',
        supportsInstruct: true,
      },
    ])
    expect(catalog.meta).toEqual({
      model: 'qwen3-tts-instruct-flash',
      updated_at: '2026-04-30',
      source: 'official',
      voice_count: 1,
    })
  })

  it('uses the requested model and empty voices when the payload is missing', () => {
    expect(normalizeVoiceCatalogPayload('cosyvoice-v3.5-plus', null)).toEqual({
      model: 'cosyvoice-v3.5-plus',
      voices: [],
      meta: {
        model: 'cosyvoice-v3.5-plus',
        updated_at: undefined,
        source: undefined,
        voice_count: 0,
      },
    })
  })

  it('preserves explicit zero voice counts', () => {
    const catalog = normalizeVoiceCatalogPayload('minimax-speech-2.8-hd', {
      voice_count: 0,
      voices: [{ id: 'male-qn-qingse', speaker: '青涩青年音', label: '青涩青年音' }],
    })

    expect(catalog.meta.voice_count).toBe(0)
  })

  it('filters invalid voices and fills missing display fields', () => {
    const catalog = normalizeVoiceCatalogPayload('minimax-speech-2.8-turbo', {
      voices: [
        null,
        { speaker: '缺少 ID', label: '缺少 ID' },
        { id: 'male-qn-qingse' },
      ],
    })

    expect(catalog.voices).toEqual([
      {
        id: 'male-qn-qingse',
        speaker: 'male-qn-qingse',
        label: 'male-qn-qingse',
        supportsInstruct: false,
      },
    ])
    expect(catalog.meta.voice_count).toBe(1)
  })
})
