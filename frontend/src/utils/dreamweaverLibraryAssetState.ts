export interface LibraryAssetLike {
  role?: unknown
  uri?: unknown
  meta?: Record<string, any> | null
}

export interface LibraryAssetImageState {
  role: string
  hasRecord: boolean
  markedMissing: boolean
  hasUri: boolean
  fileAvailable: boolean
  safetyBlocked: boolean
  placeholderMarked: boolean
  placeholder: boolean
  hasRenderableImage: boolean
}

function normalizeRoleSet(missingRoleSet?: Set<string> | ReadonlyArray<string> | null): Set<string> {
  if (missingRoleSet instanceof Set) return missingRoleSet
  if (!Array.isArray(missingRoleSet)) return new Set<string>()
  return new Set(missingRoleSet.map((role) => String(role || '').trim()).filter(Boolean))
}

function resolveGenerationSelector(meta: Record<string, any>): string {
  const generation = meta?.generation
  if (!generation || typeof generation !== 'object') return ''
  const selector = (generation as Record<string, any>).selector
  return typeof selector === 'string' ? selector.trim().toLowerCase() : ''
}

export function resolveLibraryAssetImageState(
  asset: LibraryAssetLike | null | undefined,
  options?: { missingRoleSet?: Set<string> | ReadonlyArray<string> | null },
): LibraryAssetImageState {
  const role = String(asset?.role || '').trim()
  const hasRecord = Boolean(asset && typeof asset === 'object')
  const missingRoles = normalizeRoleSet(options?.missingRoleSet || null)
  const markedMissing = Boolean(role && missingRoles.has(role))

  const uri = String(asset?.uri || '').trim()
  const hasUri = Boolean(uri)

  const meta = asset?.meta && typeof asset.meta === 'object' ? asset.meta : {}
  const fileAvailableRaw = (meta as Record<string, any>).file_available
  const fileAvailableByMeta = typeof fileAvailableRaw === 'boolean' ? fileAvailableRaw : null
  const safetyBlocked = Boolean((meta as Record<string, any>).safety_blocked)
  const generationSelector = resolveGenerationSelector(meta as Record<string, any>)
  const placeholderMarked =
    Boolean((meta as Record<string, any>).placeholder) ||
    Boolean((meta as Record<string, any>).is_placeholder) ||
    Boolean((meta as Record<string, any>).mock_placeholder) ||
    Boolean((meta as Record<string, any>).safety_placeholder) ||
    generationSelector.includes('placeholder')

  const fileAvailable = (fileAvailableByMeta !== null ? fileAvailableByMeta : hasUri) && !markedMissing
  const placeholder = hasRecord && (markedMissing || !fileAvailable || safetyBlocked || placeholderMarked)
  const hasRenderableImage = hasRecord && fileAvailable && !safetyBlocked && !placeholderMarked && !markedMissing

  return {
    role,
    hasRecord,
    markedMissing,
    hasUri,
    fileAvailable,
    safetyBlocked,
    placeholderMarked,
    placeholder,
    hasRenderableImage,
  }
}

export function hasRenderableLibraryImage(
  asset: LibraryAssetLike | null | undefined,
  options?: { missingRoleSet?: Set<string> | ReadonlyArray<string> | null },
): boolean {
  return resolveLibraryAssetImageState(asset, options).hasRenderableImage
}
