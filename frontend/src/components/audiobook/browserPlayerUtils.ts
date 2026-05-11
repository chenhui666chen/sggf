import {
  buildAudiobookChapterAssetUuid,
  buildAudiobookLabelsAssetUuid,
  buildAudiobookSubtitleAssetUuid,
} from '../../utils/audiobookAssetIds'

export {
  buildAudiobookChapterAssetUuid,
  buildAudiobookLabelsAssetUuid,
  buildAudiobookSubtitleAssetUuid,
} from '../../utils/audiobookAssetIds'

export type SubtitleFormat = 'srt' | 'vtt' | 'ass'

export interface BrowserPlayerStateSnapshot {
  currentChapterIndex: number
  currentTime: number
  volume: number
  subtitleFormat: SubtitleFormat
  showSubtitles: boolean
  wasPlaying: boolean
}

export interface BrowserPlayerTimedSegmentLike {
  start_time?: number
  end_time?: number
}

export interface BrowserPlayerTimedSegment<T extends BrowserPlayerTimedSegmentLike> {
  segment: T
  index: number
}

export interface BrowserPlayerCacheChapterLike {
  chapter_id: number
  chapter_number?: number | null
  chapter_title?: string | null
  audio_url?: string | null
  subtitle_url?: string | null
  audacity_labels_url?: string | null
}

export interface BrowserPlayerCacheAssetDescriptor {
  assetUuid: string
  mediaKind: string
  sourceModule: 'audiobook'
  title: string
  sourceUri: string | null
  previewUri: string | null
  downloadUri: string | null
  metadata: Record<string, unknown>
}

export interface BrowserPlayerBlobResponse {
  data: Blob
  headers?: Record<string, unknown>
}

export type BrowserPlayerCachedBlobInput = BrowserPlayerCacheAssetDescriptor & {
  blob: Blob
  mimeType: string
  fileSize: number
}

export interface BrowserPlayerResolvedAudioSource {
  blob: Blob
  usingLocalAsset: boolean
}

type BrowserPlayerStateStorage = Pick<Storage, 'getItem' | 'removeItem' | 'setItem'>

const PLAYER_STATE_STORAGE_PREFIX = 'audiobook_browser_player_state_v1'
const BROWSER_PLAYER_STATE_TTL_MS = 7 * 24 * 60 * 60 * 1000

export const DEFAULT_PLAYER_STATE: BrowserPlayerStateSnapshot = {
  currentChapterIndex: 0,
  currentTime: 0,
  volume: 1,
  subtitleFormat: 'srt',
  showSubtitles: true,
  wasPlaying: false,
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

export function buildPlayerStateKey(projectId: number): string {
  return `${PLAYER_STATE_STORAGE_PREFIX}:${projectId}`
}

const clampChapterIndex = (index: number, total: number): number => {
  if (total <= 0) return 0
  return Math.min(Math.max(index, 0), total - 1)
}

const getFiniteNumber = (value: unknown, fallback: number): number => {
  const nextValue = Number(value)
  return Number.isFinite(nextValue) ? nextValue : fallback
}

export const normalizeSubtitleFormat = (value: unknown): SubtitleFormat =>
  value === 'vtt' || value === 'ass' ? value : 'srt'

export const formatBrowserPlayerTime = (seconds: number): string => {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, seconds) : 0
  const mins = Math.floor(safeSeconds / 60)
  const secs = Math.floor(safeSeconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export const buildTimedSegments = <T extends BrowserPlayerTimedSegmentLike>(
  segments: readonly T[] | null | undefined,
): Array<BrowserPlayerTimedSegment<T>> =>
  (segments ?? [])
    .map((segment, index) => ({ segment, index }))
    .filter(
      ({ segment }) =>
        typeof segment.start_time === 'number' &&
        typeof segment.end_time === 'number' &&
        segment.end_time > segment.start_time,
    )
    .sort((a, b) => (a.segment.start_time ?? 0) - (b.segment.start_time ?? 0))

export const findTimedSegmentIndexByTime = <T extends BrowserPlayerTimedSegmentLike>(
  timedSegments: readonly BrowserPlayerTimedSegment<T>[],
  time: number,
): number | null => {
  if (!timedSegments.length) return null

  let low = 0
  let high = timedSegments.length - 1

  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    const { segment, index } = timedSegments[mid]
    const startTime = segment.start_time ?? 0
    const endTime = segment.end_time ?? 0

    if (time >= startTime && time < endTime) {
      return index
    }

    if (time < startTime) {
      high = mid - 1
    } else {
      low = mid + 1
    }
  }

  return null
}

const getChapterNumber = (
  chapter: Pick<BrowserPlayerCacheChapterLike, 'chapter_number'>,
  chapterIndex: number,
) => chapter.chapter_number ?? chapterIndex + 1

const getChapterTitle = (
  chapter: Pick<BrowserPlayerCacheChapterLike, 'chapter_id' | 'chapter_title'>,
) => chapter.chapter_title || `chapter_${chapter.chapter_id}`

const buildBaseCacheMetadata = ({
  projectId,
  chapter,
  chapterIndex,
}: {
  projectId: number
  chapter: BrowserPlayerCacheChapterLike
  chapterIndex: number
}) => ({
  audiobook_project_id: projectId,
  chapter_id: chapter.chapter_id,
  chapter_number: getChapterNumber(chapter, chapterIndex),
})

export const buildCachedChapterAudioAssetDescriptor = ({
  projectId,
  chapter,
  chapterIndex,
}: {
  projectId: number
  chapter: BrowserPlayerCacheChapterLike
  chapterIndex: number
}): BrowserPlayerCacheAssetDescriptor => ({
  assetUuid: buildAudiobookChapterAssetUuid(projectId, chapter.chapter_id),
  mediaKind: 'audio',
  sourceModule: 'audiobook',
  title: chapter.chapter_title || `第${getChapterNumber(chapter, chapterIndex)}章 音频`,
  sourceUri: chapter.audio_url || null,
  previewUri: chapter.audio_url || null,
  downloadUri: chapter.audio_url || null,
  metadata: {
    ...buildBaseCacheMetadata({ projectId, chapter, chapterIndex }),
    chapter_title: chapter.chapter_title || null,
  },
})

export const buildCachedSubtitleAssetDescriptor = ({
  projectId,
  chapter,
  chapterIndex,
  subtitleFormat,
}: {
  projectId: number
  chapter: BrowserPlayerCacheChapterLike
  chapterIndex: number
  subtitleFormat: SubtitleFormat
}): BrowserPlayerCacheAssetDescriptor => {
  const subtitleUri = chapter.subtitle_url ? `${chapter.subtitle_url}?format=${subtitleFormat}` : null
  return {
    assetUuid: buildAudiobookSubtitleAssetUuid(projectId, chapter.chapter_id, subtitleFormat),
    mediaKind: 'subtitle',
    sourceModule: 'audiobook',
    title: `${getChapterTitle(chapter)}.${subtitleFormat}`,
    sourceUri: subtitleUri,
    previewUri: subtitleUri,
    downloadUri: subtitleUri,
    metadata: {
      ...buildBaseCacheMetadata({ projectId, chapter, chapterIndex }),
      subtitle_format: subtitleFormat,
    },
  }
}

export const buildCachedAudacityLabelsAssetDescriptor = ({
  projectId,
  chapter,
  chapterIndex,
}: {
  projectId: number
  chapter: BrowserPlayerCacheChapterLike
  chapterIndex: number
}): BrowserPlayerCacheAssetDescriptor => ({
  assetUuid: buildAudiobookLabelsAssetUuid(projectId, chapter.chapter_id),
  mediaKind: 'subtitle',
  sourceModule: 'audiobook',
  title: `${getChapterTitle(chapter)}.labels.txt`,
  sourceUri: chapter.audacity_labels_url || null,
  previewUri: chapter.audacity_labels_url || null,
  downloadUri: chapter.audacity_labels_url || null,
  metadata: {
    ...buildBaseCacheMetadata({ projectId, chapter, chapterIndex }),
    subtitle_format: 'labels',
  },
})

export function normalizePlayerStateSnapshot(
  raw: unknown,
  totalChapters: number,
): BrowserPlayerStateSnapshot {
  if (!isRecord(raw)) {
    return DEFAULT_PLAYER_STATE
  }

  return {
    currentChapterIndex: clampChapterIndex(
      getFiniteNumber(raw.currentChapterIndex, DEFAULT_PLAYER_STATE.currentChapterIndex),
      totalChapters,
    ),
    currentTime: Math.max(0, getFiniteNumber(raw.currentTime, DEFAULT_PLAYER_STATE.currentTime)),
    volume: Math.min(1, Math.max(0, getFiniteNumber(raw.volume, DEFAULT_PLAYER_STATE.volume))),
    subtitleFormat: normalizeSubtitleFormat(raw.subtitleFormat),
    showSubtitles: typeof raw.showSubtitles === 'boolean'
      ? raw.showSubtitles
      : DEFAULT_PLAYER_STATE.showSubtitles,
    wasPlaying: raw.wasPlaying === true,
  }
}

export const readStoredBrowserPlayerState = (
  storage: BrowserPlayerStateStorage,
  projectId: number,
  totalChapters: number,
): BrowserPlayerStateSnapshot => {
  const storageKey = buildPlayerStateKey(projectId)
  let raw: string | null = null
  try {
    raw = storage.getItem(storageKey)
  } catch {
    return DEFAULT_PLAYER_STATE
  }

  if (!raw) {
    return DEFAULT_PLAYER_STATE
  }

  try {
    const parsed = JSON.parse(raw)
    if (
      isRecord(parsed)
      && typeof parsed.savedAt === 'number'
      && Number.isFinite(parsed.savedAt)
      && Date.now() - parsed.savedAt > BROWSER_PLAYER_STATE_TTL_MS
    ) {
      try {
        storage.removeItem(storageKey)
      } catch {
        // localStorage 不可用或已失效时忽略过期状态清理失败。
      }
      return DEFAULT_PLAYER_STATE
    }

    return normalizePlayerStateSnapshot(parsed, totalChapters)
  } catch {
    try {
      storage.removeItem(storageKey)
    } catch {
      // localStorage 不可用时忽略播放器状态清理失败。
    }
    return DEFAULT_PLAYER_STATE
  }
}

export const writeStoredBrowserPlayerState = (
  storage: BrowserPlayerStateStorage,
  projectId: number,
  snapshot: BrowserPlayerStateSnapshot,
): boolean => {
  try {
    storage.setItem(
      buildPlayerStateKey(projectId),
      JSON.stringify({
        ...snapshot,
        savedAt: Date.now(),
      }),
    )
    return true
  } catch {
    return false
  }
}

export const resolveCachedBrowserPlayerBlob = async ({
  cachedAsset,
  getCachedBlob,
  fetchRemoteBlob,
  saveCachedAsset,
  fallbackMimeType = 'text/plain',
  onCacheSaveError,
}: {
  cachedAsset: BrowserPlayerCacheAssetDescriptor
  getCachedBlob: (assetUuid: string) => Promise<Blob | null>
  fetchRemoteBlob: () => Promise<BrowserPlayerBlobResponse>
  saveCachedAsset: (input: BrowserPlayerCachedBlobInput) => Promise<unknown>
  fallbackMimeType?: string
  onCacheSaveError?: (error: unknown) => void
}): Promise<Blob> => {
  const cachedBlob = await getCachedBlob(cachedAsset.assetUuid).catch(() => null)
  if (cachedBlob) {
    return cachedBlob
  }

  const response = await fetchRemoteBlob()
  const remoteBlob = response.data
  const responseContentType = response.headers?.['content-type']
  try {
    await saveCachedAsset({
      ...cachedAsset,
      blob: remoteBlob,
      mimeType: remoteBlob.type || (typeof responseContentType === 'string' ? responseContentType : fallbackMimeType),
      fileSize: remoteBlob.size,
    })
  } catch (error) {
    onCacheSaveError?.(error)
  }

  return remoteBlob
}

export const resolveBrowserPlayerAudioSource = async ({
  cachedAsset,
  getCachedBlob,
  fetchRemoteBlob,
  saveCachedAsset,
  shouldCancel,
  onCacheSaveError,
}: {
  cachedAsset: BrowserPlayerCacheAssetDescriptor
  getCachedBlob: (assetUuid: string) => Promise<Blob | null>
  fetchRemoteBlob: () => Promise<BrowserPlayerBlobResponse>
  saveCachedAsset: (input: BrowserPlayerCachedBlobInput) => Promise<unknown>
  shouldCancel?: () => boolean
  onCacheSaveError?: (error: unknown) => void
}): Promise<BrowserPlayerResolvedAudioSource | null> => {
  const cachedBlob = await getCachedBlob(cachedAsset.assetUuid).catch(() => null)
  if (shouldCancel?.()) {
    return null
  }
  if (cachedBlob) {
    return {
      blob: cachedBlob,
      usingLocalAsset: true,
    }
  }

  const response = await fetchRemoteBlob()
  const remoteBlob = response.data
  const responseContentType = response.headers?.['content-type']
  try {
    await saveCachedAsset({
      ...cachedAsset,
      blob: remoteBlob,
      mimeType: remoteBlob.type || (typeof responseContentType === 'string' ? responseContentType : 'audio/mpeg'),
      fileSize: remoteBlob.size,
    })
  } catch (error) {
    onCacheSaveError?.(error)
  }
  if (shouldCancel?.()) {
    return null
  }

  return {
    blob: remoteBlob,
    usingLocalAsset: false,
  }
}
