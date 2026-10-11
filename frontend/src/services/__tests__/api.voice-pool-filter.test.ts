import { afterEach, describe, expect, it, vi } from 'vitest'

import axios from 'axios'

import { apiClient } from '../api'

afterEach(() => {
  vi.restoreAllMocks()
})

type GetSpy = ReturnType<typeof spyClientGet>

function spyClientGet() {
  return vi.spyOn(
    (
      apiClient as unknown as {
        client: { get: (...args: unknown[]) => Promise<unknown> }
      }
    ).client,
    'get',
  )
}

const resolveRequestUri = (path: string, config: Record<string, unknown>) =>
  axios.getUri({
    url: path,
    params: config.params,
    paramsSerializer: config.paramsSerializer,
  } as never)

describe('getPublicVoicePool tag filters', () => {
  it('sends repeated query params so the backend OR-filters within a dimension', async () => {
    const getMock = spyClientGet().mockResolvedValue({ data: { voices: [], total: 0 } })

    await apiClient.getPublicVoicePool({
      timbre_tags: ['clear', 'slightly_husky'],
      emotion_tags: ['sad'],
      limit: 50,
    })

    expect(getMock).toHaveBeenCalledTimes(1)
    const [path, config] = getMock.mock.calls[0] as [string, Record<string, unknown>]
    expect(path).toBe('/api/v1/audiobook/voice-pool/public')

    const uri = resolveRequestUri(path, config)
    expect(uri).toContain('timbre_tags=clear')
    expect(uri).toContain('timbre_tags=slightly_husky')
    expect(uri).toContain('emotion_tags=sad')
    expect(uri).not.toContain('timbre_tags%5B%5D')
    expect(uri).not.toContain('timbre_tags[]')
  })

  it('omits tag filters when the caller selects none', async () => {
    const getMock = spyClientGet().mockResolvedValue({ data: { voices: [], total: 0 } })

    await apiClient.getPublicVoicePool({ limit: 20 })

    const [path, config] = (getMock as GetSpy).mock.calls[0] as [string, Record<string, unknown>]
    const uri = resolveRequestUri(path, config)
    expect(uri).toContain('limit=20')
    expect(uri).not.toContain('timbre_tags')
    expect(uri).not.toContain('scenario_tags')
    expect(uri).not.toContain('emotion_tags')
  })
})
