import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api'

const previewPayload = {
  text: 'preview text',
  voice_id: 'unit-voice',
  instruction: 'please speak calmly',
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('previewTTSCached', () => {
  it('uses explicit audio_url from the preview cache JSON contract', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          audio_url: 'https://cdn.example/preview.mp3',
          blob: null,
          cache_hit: true,
          storage: 'oss',
          response_format: 'mp3',
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiClient.previewTTSCached(previewPayload)

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/audiobook/tts/preview-cached'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(previewPayload),
      }),
    )
    expect(result).toEqual({ audioUrl: 'https://cdn.example/preview.mp3', blob: null })
  })

  it('decodes base64 audio from the preview cache JSON fallback', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          audio_url: null,
          blob: 'UklGRnVuaXQtYXVkaW8=',
          cache_hit: false,
          storage: 'blob',
          response_format: 'wav',
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiClient.previewTTSCached(previewPayload)

    expect(result.audioUrl).toBeNull()
    expect(result.blob).toBeInstanceOf(Blob)
    expect(result.blob?.type).toBe('audio/wav')
    await expect(result.blob?.text()).resolves.toBe('RIFFunit-audio')
  })
})
