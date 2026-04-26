export type UserAssetSourceAudiobookFocusMode = 'script-editor'

export type UserAssetSourceAudiobookRouteRequest = {
  audiobookProjectId: number | null
  chapterId: number | null
  focus: UserAssetSourceAudiobookFocusMode | null
}

export type DreamweaverRunSourceNavigationPlan = {
  restoreKey: string
  runId: string
}

export type DreamweaverLibrarySourceActivationPlan = {
  focusKey: string
  characterEntityId: number | null
  shouldOpenCharacterViews: boolean
}

export type DreamweaverLibrarySourceScrollPlan = {
  scrollKey: string
  targetSelector: string | null
  fallbackSelector: string | null
}

export type AudiobookSourceFocusPlan = {
  focusKey: string
  targetAudiobookProjectId: number
  chapterId: number
  focusMode: UserAssetSourceAudiobookFocusMode
  shouldRefreshProject: boolean
}

function readPositiveInt(value: string | null | undefined): number | null {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

function readTrimmedString(value: string | null | undefined): string | null {
  const normalized = String(value || '').trim()
  return normalized || null
}

export function readUserAssetSourceRunId(searchParams: URLSearchParams): string | null {
  return readTrimmedString(searchParams.get('runId'))
}

export function readUserAssetSourceLibraryAssetId(searchParams: URLSearchParams): number | null {
  return readPositiveInt(searchParams.get('assetId'))
}

export function readUserAssetSourceAudiobookRouteRequest(
  searchParams: URLSearchParams,
): UserAssetSourceAudiobookRouteRequest {
  const rawFocus = readTrimmedString(searchParams.get('focus'))?.toLowerCase() ?? null

  return {
    audiobookProjectId: readPositiveInt(searchParams.get('audiobookProjectId')),
    chapterId: readPositiveInt(searchParams.get('chapterId')),
    focus: rawFocus === 'script-editor' ? 'script-editor' : null,
  }
}

export function buildUserAssetSourceRestoreKey(
  ...parts: Array<string | number | null | undefined>
): string | null {
  const normalizedParts = parts
    .map((part) => {
      if (part == null) return null
      const normalized = typeof part === 'number' ? String(part) : String(part).trim()
      return normalized || null
    })
    .filter((part): part is string => Boolean(part))

  return normalizedParts.length === parts.length ? normalizedParts.join(':') : null
}

export function buildDreamweaverRunSourceNavigationPlan(options: {
  selectedProjectId: number | null
  requestedRunId: string | null
  handledRestoreKey?: string | null
}): DreamweaverRunSourceNavigationPlan | null {
  const { selectedProjectId, requestedRunId, handledRestoreKey = null } = options
  const restoreKey = buildUserAssetSourceRestoreKey(selectedProjectId, requestedRunId)
  if (!restoreKey || handledRestoreKey === restoreKey || !requestedRunId) {
    return null
  }

  return {
    restoreKey,
    runId: requestedRunId,
  }
}

export function buildDreamweaverLibrarySourceActivationPlan(options: {
  projectId: number
  requestedLibraryAssetId: number | null
  requestedCharacterEntityId: number | null
  loading: boolean
  handledFocusKey?: string | null
}): DreamweaverLibrarySourceActivationPlan | null {
  const {
    projectId,
    requestedLibraryAssetId,
    requestedCharacterEntityId,
    loading,
    handledFocusKey = null,
  } = options
  if (loading || !requestedLibraryAssetId) {
    return null
  }

  const focusKey = buildUserAssetSourceRestoreKey(projectId, requestedLibraryAssetId)
  if (!focusKey || handledFocusKey === focusKey) {
    return null
  }

  return {
    focusKey,
    characterEntityId: requestedCharacterEntityId,
    shouldOpenCharacterViews: Boolean(requestedCharacterEntityId),
  }
}

export function buildDreamweaverLibrarySourceScrollPlan(options: {
  projectId: number
  requestedLibraryAssetId: number | null
  requestedCharacterEntityId: number | null
  characterViewsOpen: boolean
  loading: boolean
  domAvailable: boolean
  handledScrollKey?: string | null
}): DreamweaverLibrarySourceScrollPlan | null {
  const {
    projectId,
    requestedLibraryAssetId,
    requestedCharacterEntityId,
    characterViewsOpen,
    loading,
    domAvailable,
    handledScrollKey = null,
  } = options
  if (!domAvailable || loading || !requestedLibraryAssetId) {
    return null
  }

  if (requestedCharacterEntityId && !characterViewsOpen) {
    return null
  }

  const scrollKey = buildUserAssetSourceRestoreKey(
    projectId,
    requestedLibraryAssetId,
    characterViewsOpen ? 'dialog' : 'grid',
  )
  if (!scrollKey || handledScrollKey === scrollKey) {
    return null
  }

  const { targetSelector, fallbackSelector } = buildUserAssetLibraryFocusSelectors(
    requestedLibraryAssetId,
    requestedCharacterEntityId,
  )

  return {
    scrollKey,
    targetSelector,
    fallbackSelector,
  }
}

export function buildAudiobookSourceFocusPlan(options: {
  selectedProjectId: number | null
  requestedAudiobookProjectId: number | null
  requestedSourceChapterId: number | null
  requestedSourceFocus: UserAssetSourceAudiobookFocusMode | null
  loadedAudiobookProjectId: number | null
  currentAudiobookProjectId: number | null
  handledFocusKey?: string | null
}): AudiobookSourceFocusPlan | null {
  const {
    selectedProjectId,
    requestedAudiobookProjectId,
    requestedSourceChapterId,
    requestedSourceFocus,
    loadedAudiobookProjectId,
    currentAudiobookProjectId,
    handledFocusKey = null,
  } = options
  if (!selectedProjectId || !requestedSourceChapterId) {
    return null
  }

  const focusMode = requestedSourceFocus || 'script-editor'
  if (focusMode !== 'script-editor') {
    return null
  }

  const targetAudiobookProjectId =
    requestedAudiobookProjectId || loadedAudiobookProjectId || currentAudiobookProjectId
  if (!targetAudiobookProjectId) {
    return null
  }

  const focusKey = buildUserAssetSourceRestoreKey(
    selectedProjectId,
    targetAudiobookProjectId,
    requestedSourceChapterId,
    focusMode,
  )
  if (!focusKey || handledFocusKey === focusKey) {
    return null
  }

  return {
    focusKey,
    targetAudiobookProjectId,
    chapterId: requestedSourceChapterId,
    focusMode,
    shouldRefreshProject: loadedAudiobookProjectId !== targetAudiobookProjectId,
  }
}

export function buildUserAssetLibraryFocusSelectors(
  assetId: number | null,
  characterEntityId: number | null,
): { targetSelector: string | null; fallbackSelector: string | null } {
  return {
    targetSelector: assetId ? `[data-library-asset-id="${assetId}"]` : null,
    fallbackSelector: characterEntityId ? `[data-library-character-entity-id="${characterEntityId}"]` : null,
  }
}
