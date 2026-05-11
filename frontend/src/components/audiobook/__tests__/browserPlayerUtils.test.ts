import { describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_PLAYER_STATE,
  buildAudiobookChapterAssetUuid,
  buildAudiobookLabelsAssetUuid,
  buildAudiobookSubtitleAssetUuid,
  buildCachedAudacityLabelsAssetDescriptor,
  buildCachedChapterAudioAssetDescriptor,
  buildCachedSubtitleAssetDescriptor,
  buildPlayerStateKey,
  buildTimedSegments,
  findTimedSegmentIndexByTime,
  formatBrowserPlayerTime,
  normalizePlayerStateSnapshot,
  normalizeSubtitleFormat,
  readStoredBrowserPlayerState,
  resolveBrowserPlayerAudioSource,
  resolveCachedBrowserPlayerBlob,
  writeStoredBrowserPlayerState,
} from '../browserPlayerUtils'

class MemoryStorage implements Pick<Storage, 'getItem' | 'removeItem' | 'setItem'> {
  private readonly values = new Map<string, string>()

  getItem(key: string) {
    return this.values.get(key) ?? null
  }

  removeItem(key: string) {
    this.values.delete(key)
  }

  setItem(key: string, value: string) {
    this.values.set(key, value)
  }
}

class ThrowingStorage implements Pick<Storage, 'getItem' | 'removeItem' | 'setItem'> {
  getItem(_key: string): string | null {
    throw new Error('storage unavailable')
  }

  removeItem(_key: string): void {
    throw new Error('storage unavailable')
  }

  setItem(_key: string, _value: string): void {
    throw new Error('storage unavailable')
  }
}

describe('browser player utils', () => {
  it('builds stable local storage and asset identifiers', () => {
    expect(buildPlayerStateKey(12)).toBe('audiobook_browser_player_state_v1:12')
    expect(buildAudiobookChapterAssetUuid(12, 34)).toBe('audiobook-12-34')
    expect(buildAudiobookSubtitleAssetUuid(12, 34, 'vtt')).toBe('audiobook-subtitle-12-34-vtt')
    expect(buildAudiobookLabelsAssetUuid(12, 34)).toBe('audiobook-labels-12-34')
  })

  it('normalizes subtitle formats', () => {
    expect(normalizeSubtitleFormat('vtt')).toBe('vtt')
    expect(normalizeSubtitleFormat('ass')).toBe('ass')
    expect(normalizeSubtitleFormat('txt')).toBe('srt')
    expect(normalizeSubtitleFormat(null)).toBe('srt')
  })

  it('formats playback time defensively', () => {
    expect(formatBrowserPlayerTime(0)).toBe('0:00')
    expect(formatBrowserPlayerTime(65.8)).toBe('1:05')
    expect(formatBrowserPlayerTime(3601)).toBe('60:01')
    expect(formatBrowserPlayerTime(-1)).toBe('0:00')
    expect(formatBrowserPlayerTime(Number.NaN)).toBe('0:00')
  })

  it('normalizes persisted player state safely', () => {
    expect(normalizePlayerStateSnapshot(null, 4)).toEqual(DEFAULT_PLAYER_STATE)
    expect(normalizePlayerStateSnapshot({
      currentChapterIndex: 99,
      currentTime: -12,
      volume: 2,
      subtitleFormat: 'vtt',
      showSubtitles: false,
      wasPlaying: 'false',
    }, 3)).toEqual({
      currentChapterIndex: 2,
      currentTime: 0,
      volume: 1,
      subtitleFormat: 'vtt',
      showSubtitles: false,
      wasPlaying: false,
    })
  })

  it('reads and writes stored browser player state safely', () => {
    const storage = new MemoryStorage()
    const projectId = 12
    const storageKey = buildPlayerStateKey(projectId)
    const now = Date.now()
    const snapshot = {
      currentChapterIndex: 1,
      currentTime: 31,
      volume: 0.6,
      subtitleFormat: 'vtt' as const,
      showSubtitles: false,
      wasPlaying: true,
    }

    expect(readStoredBrowserPlayerState(storage, projectId, 3)).toEqual(DEFAULT_PLAYER_STATE)
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now)
    expect(writeStoredBrowserPlayerState(storage, projectId, snapshot)).toBe(true)
    nowSpy.mockRestore()

    expect(JSON.parse(storage.getItem(storageKey) as string)).toMatchObject({
      ...snapshot,
      savedAt: now,
    })
    expect(readStoredBrowserPlayerState(storage, projectId, 3)).toEqual(snapshot)

    storage.setItem(storageKey, JSON.stringify({
      currentChapterIndex: 99,
      currentTime: -1,
      volume: 2,
      subtitleFormat: 'bad',
      showSubtitles: true,
      wasPlaying: 'false',
    }))
    expect(readStoredBrowserPlayerState(storage, projectId, 2)).toEqual({
      currentChapterIndex: 1,
      currentTime: 0,
      volume: 1,
      subtitleFormat: 'srt',
      showSubtitles: true,
      wasPlaying: false,
    })

    storage.setItem(storageKey, '{bad-json')
    expect(readStoredBrowserPlayerState(storage, projectId, 2)).toEqual(DEFAULT_PLAYER_STATE)
    expect(storage.getItem(storageKey)).toBeNull()

    expect(readStoredBrowserPlayerState(new ThrowingStorage(), projectId, 2)).toEqual(DEFAULT_PLAYER_STATE)
    expect(writeStoredBrowserPlayerState(new ThrowingStorage(), projectId, snapshot)).toBe(false)
  })

  it('expires stored browser player state after the TTL window', () => {
    const storage = new MemoryStorage()
    const projectId = 12
    const storageKey = buildPlayerStateKey(projectId)
    const snapshot = {
      currentChapterIndex: 2,
      currentTime: 88,
      volume: 0.9,
      subtitleFormat: 'ass' as const,
      showSubtitles: true,
      wasPlaying: false,
    }
    const ttlMs = 7 * 24 * 60 * 60 * 1000
    const now = 1_700_000_000_000
    const savedAt = now - ttlMs - 1

    storage.setItem(storageKey, JSON.stringify({
      ...snapshot,
      savedAt,
    }))

    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(now)
    expect(readStoredBrowserPlayerState(storage, projectId, 4)).toEqual(DEFAULT_PLAYER_STATE)
    nowSpy.mockRestore()
    expect(storage.getItem(storageKey)).toBeNull()
  })

  it('builds timed segments and finds active segment by playback time', () => {
    const timedSegments = buildTimedSegments([
      { text: 'late', start_time: 10, end_time: 12 },
      { text: 'invalid', start_time: 8, end_time: 8 },
      { text: 'early', start_time: 1, end_time: 3 },
      { text: 'missing' },
    ])

    expect(timedSegments.map(({ index, segment }) => ({ index, text: segment.text }))).toEqual([
      { index: 2, text: 'early' },
      { index: 0, text: 'late' },
    ])
    expect(findTimedSegmentIndexByTime(timedSegments, 0.9)).toBeNull()
    expect(findTimedSegmentIndexByTime(timedSegments, 1)).toBe(2)
    expect(findTimedSegmentIndexByTime(timedSegments, 11)).toBe(0)
    expect(findTimedSegmentIndexByTime(timedSegments, 12)).toBeNull()
  })

  it('builds cached asset descriptors for player downloads', () => {
    const chapter = {
      chapter_id: 34,
      chapter_number: null,
      chapter_title: 'Opening',
      audio_url: '/audio/34',
      subtitle_url: '/subtitle/34',
      audacity_labels_url: '/labels/34',
    }

    expect(buildCachedChapterAudioAssetDescriptor({
      projectId: 12,
      chapter,
      chapterIndex: 2,
    })).toEqual({
      assetUuid: 'audiobook-12-34',
      mediaKind: 'audio',
      sourceModule: 'audiobook',
      title: 'Opening',
      sourceUri: '/audio/34',
      previewUri: '/audio/34',
      downloadUri: '/audio/34',
      metadata: {
        audiobook_project_id: 12,
        chapter_id: 34,
        chapter_number: 3,
        chapter_title: 'Opening',
      },
    })

    expect(buildCachedSubtitleAssetDescriptor({
      projectId: 12,
      chapter,
      chapterIndex: 2,
      subtitleFormat: 'ass',
    })).toMatchObject({
      assetUuid: 'audiobook-subtitle-12-34-ass',
      mediaKind: 'subtitle',
      title: 'Opening.ass',
      sourceUri: '/subtitle/34?format=ass',
      metadata: {
        subtitle_format: 'ass',
      },
    })

    expect(buildCachedAudacityLabelsAssetDescriptor({
      projectId: 12,
      chapter,
      chapterIndex: 2,
    })).toMatchObject({
      assetUuid: 'audiobook-labels-12-34',
      mediaKind: 'subtitle',
      title: 'Opening.labels.txt',
      sourceUri: '/labels/34',
      metadata: {
        subtitle_format: 'labels',
      },
    })
  })

  it('resolves browser player download blobs from cache before fetching remotely', async () => {
    const cachedBlob = new Blob(['cached'], { type: 'text/plain' })
    const remoteBlob = new Blob(['remote'], { type: 'text/vtt' })
    const cachedAsset = buildCachedSubtitleAssetDescriptor({
      projectId: 12,
      chapter: {
        chapter_id: 34,
        chapter_title: 'Opening',
        subtitle_url: '/subtitle/34',
      },
      chapterIndex: 0,
      subtitleFormat: 'vtt',
    })
    const savedInputs: unknown[] = []
    const cacheErrors: unknown[] = []

    await expect(resolveCachedBrowserPlayerBlob({
      cachedAsset,
      getCachedBlob: async () => cachedBlob,
      fetchRemoteBlob: async () => {
        throw new Error('should not fetch')
      },
      saveCachedAsset: async (input) => {
        savedInputs.push(input)
      },
    })).resolves.toBe(cachedBlob)
    expect(savedInputs).toEqual([])

    await expect(resolveCachedBrowserPlayerBlob({
      cachedAsset,
      getCachedBlob: async () => null,
      fetchRemoteBlob: async () => ({
        data: remoteBlob,
        headers: { 'content-type': 'text/custom' },
      }),
      saveCachedAsset: async (input) => {
        savedInputs.push(input)
      },
    })).resolves.toBe(remoteBlob)
    expect(savedInputs[0]).toMatchObject({
      assetUuid: 'audiobook-subtitle-12-34-vtt',
      blob: remoteBlob,
      mimeType: 'text/vtt',
      fileSize: remoteBlob.size,
    })

    await expect(resolveCachedBrowserPlayerBlob({
      cachedAsset,
      getCachedBlob: async () => null,
      fetchRemoteBlob: async () => ({
        data: new Blob(['remote']),
        headers: { 'content-type': 'text/custom' },
      }),
      saveCachedAsset: async () => {
        throw new Error('cache failed')
      },
      onCacheSaveError: (error) => {
        cacheErrors.push(error)
      },
    })).resolves.toBeInstanceOf(Blob)
    expect(cacheErrors).toHaveLength(1)
  })

  it('resolves audio sources with cache status and cancellation checks', async () => {
    const cachedAudio = new Blob(['cached'], { type: 'audio/mpeg' })
    const remoteAudio = new Blob(['remote'])
    const cachedAsset = buildCachedChapterAudioAssetDescriptor({
      projectId: 12,
      chapter: {
        chapter_id: 34,
        chapter_title: 'Opening',
        audio_url: '/audio/34',
      },
      chapterIndex: 0,
    })
    const savedInputs: unknown[] = []
    const cacheErrors: unknown[] = []
    let cancelled = false

    await expect(resolveBrowserPlayerAudioSource({
      cachedAsset,
      getCachedBlob: async () => cachedAudio,
      fetchRemoteBlob: async () => {
        throw new Error('should not fetch')
      },
      saveCachedAsset: async (input) => {
        savedInputs.push(input)
      },
    })).resolves.toEqual({
      blob: cachedAudio,
      usingLocalAsset: true,
    })

    await expect(resolveBrowserPlayerAudioSource({
      cachedAsset,
      getCachedBlob: async () => null,
      fetchRemoteBlob: async () => ({
        data: remoteAudio,
        headers: { 'content-type': 'audio/custom' },
      }),
      saveCachedAsset: async (input) => {
        savedInputs.push(input)
      },
    })).resolves.toEqual({
      blob: remoteAudio,
      usingLocalAsset: false,
    })
    expect(savedInputs[0]).toMatchObject({
      assetUuid: 'audiobook-12-34',
      blob: remoteAudio,
      mimeType: 'audio/custom',
      fileSize: remoteAudio.size,
    })

    await expect(resolveBrowserPlayerAudioSource({
      cachedAsset,
      getCachedBlob: async () => null,
      fetchRemoteBlob: async () => ({
        data: new Blob(['remote'], { type: 'audio/wav' }),
      }),
      saveCachedAsset: async () => {
        throw new Error('cache failed')
      },
      onCacheSaveError: (error) => {
        cacheErrors.push(error)
      },
    })).resolves.toMatchObject({
      usingLocalAsset: false,
    })
    expect(cacheErrors).toHaveLength(1)

    cancelled = true
    await expect(resolveBrowserPlayerAudioSource({
      cachedAsset,
      getCachedBlob: async () => cachedAudio,
      fetchRemoteBlob: async () => {
        throw new Error('should not fetch')
      },
      saveCachedAsset: async (input) => {
        savedInputs.push(input)
      },
      shouldCancel: () => cancelled,
    })).resolves.toBeNull()
  })
})
