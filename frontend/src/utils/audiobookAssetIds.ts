export const buildAudiobookChapterAssetUuid = (
  audiobookProjectId: number,
  chapterId: number,
): string => `audiobook-${audiobookProjectId}-${chapterId}`

export const buildAudiobookSubtitleAssetUuid = (
  audiobookProjectId: number,
  chapterId: number,
  subtitleFormat: string,
): string => `audiobook-subtitle-${audiobookProjectId}-${chapterId}-${subtitleFormat}`

export const buildAudiobookLabelsAssetUuid = (
  audiobookProjectId: number,
  chapterId: number,
): string => `audiobook-labels-${audiobookProjectId}-${chapterId}`
