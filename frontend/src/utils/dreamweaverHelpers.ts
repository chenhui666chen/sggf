export {
  buildProtectedMergedVideoUrl,
  clearPersistedDreamWeaverRun,
  dreamweaverRunStorageKey,
  extractMergedVideoFromContract,
  isPlaceholderEntityName,
  libraryAssetToCssAspectRatio,
  mergeRunResult,
  ratioIsPortrait,
  ratioToCssAspectRatio,
  readPersistedDreamWeaverRun,
  writePersistedDreamWeaverRun,
} from './dreamweaver'

export function buildProtectedLibraryAssetUrl(assetId: number): string {
  return `protected://dreamweaver-library/${assetId}`
}

export function formatPath(value: unknown): string | null {
  if (!value || typeof value !== 'string') return null
  const parts = value.split(/[\\/]+/).filter(Boolean)
  return parts.slice(-2).join('/')
}

export function formatPaths(value: unknown): string | null {
  if (!Array.isArray(value)) return null
  const formatted = value.map(formatPath).filter(Boolean)
  return formatted.length ? formatted.join('  ') : null
}
