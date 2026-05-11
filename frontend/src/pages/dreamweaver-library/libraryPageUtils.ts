import {
  CHARACTER_VIEW_ORDER,
  characterViewLabel,
  characterViewRole,
  parseLibraryRole,
  type CharacterView,
} from '@/utils/dreamweaverLibraryRole'
import {
  STYLE_PRESETS,
  IMAGE_RATIOS,
  STYLE_PRESET_LABELS,
} from '@/constants/dreamweaver'

export type StylePresetValue = typeof STYLE_PRESETS[keyof typeof STYLE_PRESETS]
export type ImageRatioValue = typeof IMAGE_RATIOS[keyof typeof IMAGE_RATIOS]

export interface LibraryAsset {
  id: number
  role: string
  uri: string
  meta?: Record<string, any>
}

export interface LibraryPayload {
  project_id: number
  spec?: Record<string, any>
  review?: Record<string, any>
  assets: LibraryAsset[]
}

export interface CollectFeedback {
  type: 'success' | 'error'
  text: string
}

export interface CollectState {
  loading: boolean
  feedback: CollectFeedback | null
}

export type CharacterCard = {
  kind: 'character'
  entityId: number
  title: string
  descriptor: string
  views: Record<CharacterView, LibraryAsset | null>
}

export type AssetCard = { kind: 'asset'; asset: LibraryAsset }

export type LibraryCard = CharacterCard | AssetCard
export type LibraryCardGroupKey = 'character' | 'scene' | 'prop' | 'other'

export const LIBRARY_CARD_GROUP_ORDER: ReadonlyArray<{ key: LibraryCardGroupKey; label: string }> = [
  { key: 'character', label: '人物' },
  { key: 'scene', label: '场景' },
  { key: 'prop', label: '道具' },
  { key: 'other', label: '其他' },
]

export function buildProtectedLibraryAssetUrl(assetId: number): string {
  return `protected://dreamweaver-library/${assetId}`
}

export function normalizeStylePresetValue(raw: any): StylePresetValue {
  const text = String(raw || '').trim()
  const allowed = new Set<string>(Object.values(STYLE_PRESETS))
  if (allowed.has(text)) return text as StylePresetValue
  if (text === STYLE_PRESET_LABELS[STYLE_PRESETS.CINEMATIC_REALISTIC]) return STYLE_PRESETS.CINEMATIC_REALISTIC
  if (text === STYLE_PRESET_LABELS[STYLE_PRESETS.ANIME]) return STYLE_PRESETS.ANIME
  if (text === STYLE_PRESET_LABELS[STYLE_PRESETS.INK_WASH]) return STYLE_PRESETS.INK_WASH
  if (text === STYLE_PRESET_LABELS[STYLE_PRESETS.CYBERPUNK]) return STYLE_PRESETS.CYBERPUNK
  return STYLE_PRESETS.CINEMATIC_REALISTIC
}

export function normalizeImageRatioValue(raw: any): ImageRatioValue {
  const text = String(raw || '').trim()
  if (text === IMAGE_RATIOS.LANDSCAPE_16_9 || text === IMAGE_RATIOS.PORTRAIT_9_16) {
    return text as ImageRatioValue
  }
  return IMAGE_RATIOS.LANDSCAPE_16_9
}

function ratioToCssAspectRatio(raw: any, fallback: string): string {
  if (typeof raw !== 'string' || !raw.trim()) return fallback
  const parts = raw.split(':').map((p) => Number.parseFloat(p.trim()))
  if (parts.length !== 2 || !Number.isFinite(parts[0]) || !Number.isFinite(parts[1]) || parts[0] <= 0 || parts[1] <= 0) return fallback
  return `${parts[0]} / ${parts[1]}`
}

export function assetToCssAspectRatio(asset: LibraryAsset, fallback: string): string {
  const meta = asset?.meta
  const rawWidth = meta?.width
  const rawHeight = meta?.height
  const width = typeof rawWidth === 'number' && Number.isFinite(rawWidth) ? rawWidth : Number.parseInt(String(rawWidth || '0'), 10)
  const height = typeof rawHeight === 'number' && Number.isFinite(rawHeight) ? rawHeight : Number.parseInt(String(rawHeight || '0'), 10)
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) return `${width} / ${height}`
  return ratioToCssAspectRatio(meta?.ratio, fallback)
}

export function assetTitle(asset: LibraryAsset): string {
  const name = asset?.meta?.entity_name
  if (typeof name === 'string' && name.trim()) return name.trim()
  return String(asset?.role || '')
}

export function isPlaceholderEntityName(value: unknown): boolean {
  const text = String(value || '').trim()
  if (!text) return true
  if (/^[?\s]+$/.test(text)) return true
  const lowered = text.toLowerCase()
  if (lowered === 'unknown' || lowered === 'n/a' || lowered === 'na') return true
  if (text === '未知' || text === '未命名' || text === '角色' || text === '人物' || text === '角色名') return true
  if (text.startsWith('lib_')) return true
  return false
}

export function getKlingProviderRef(asset: LibraryAsset | null): { subjectId: string | null; synced: boolean } {
  if (!asset?.meta?.provider_refs) return { subjectId: null, synced: false }
  const klingRef = (asset.meta.provider_refs as Record<string, any>)?.kling
  if (!klingRef) return { subjectId: null, synced: false }
  return {
    subjectId: String(klingRef.subject_id || klingRef.element_id || ''),
    synced: String(klingRef.source || '') === 'auto_sync',
  }
}

export function buildLibraryCards(
  assets: LibraryAsset[],
  assetsByRole: Map<string, LibraryAsset>,
  characterNameById: Map<number, string>,
  spec?: Record<string, any>,
): LibraryCard[] {
  const specCharacters = Array.isArray(spec?.characters) ? (spec!.characters as any[]) : []
  const specScenes = Array.isArray(spec?.scenes) ? (spec!.scenes as any[]) : []
  const specProps = Array.isArray(spec?.props) ? (spec!.props as any[]) : []

  const usedRoles = new Set<string>()
  const out: LibraryCard[] = []

  for (const item of specCharacters) {
    const entityId = Number.parseInt(String(item?.entity_id ?? ''), 10)
    if (!Number.isFinite(entityId) || entityId <= 0) continue
    const rawName = String(item?.name || '').trim()
    const mappedName = characterNameById.get(entityId) || ''
    const title = isPlaceholderEntityName(rawName) ? mappedName || `角色#${entityId}` : rawName
    const descriptor = String(item?.descriptor || '').trim()
    const views = Object.fromEntries(
      CHARACTER_VIEW_ORDER.map((view) => [view, assetsByRole.get(characterViewRole(view, entityId)) || null]),
    ) as Record<CharacterView, LibraryAsset | null>
    for (const viewAsset of Object.values(views)) {
      if (viewAsset?.role) usedRoles.add(String(viewAsset.role).trim())
    }
    out.push({ kind: 'character', entityId, title, descriptor, views })
  }

  const pushRoleIfExists = (role: string) => {
    const asset = assetsByRole.get(role)
    if (!asset) return
    if (usedRoles.has(role)) return
    out.push({ kind: 'asset', asset })
    usedRoles.add(role)
  }

  for (const item of specScenes) {
    const entityId = Number.parseInt(String(item?.entity_id ?? ''), 10)
    if (!Number.isFinite(entityId) || entityId <= 0) continue
    pushRoleIfExists(`lib_scene_card:${entityId}`)
  }
  for (const item of specProps) {
    const entityId = Number.parseInt(String(item?.entity_id ?? ''), 10)
    if (!Number.isFinite(entityId) || entityId <= 0) continue
    pushRoleIfExists(`lib_prop_card:${entityId}`)
  }

  for (const asset of assets) {
    const role = String(asset?.role || '').trim()
    if (!role || usedRoles.has(role)) continue
    const parsed = parseLibraryRole(role)
    if (parsed.entityType === 'character') continue
    out.push({ kind: 'asset', asset })
    usedRoles.add(role)
  }
  return out
}

export function buildCardGroups(cards: LibraryCard[]): Record<LibraryCardGroupKey, LibraryCard[]> {
  const groups: Record<LibraryCardGroupKey, LibraryCard[]> = {
    character: [],
    scene: [],
    prop: [],
    other: [],
  }
  for (const card of cards) {
    if (card.kind === 'character') {
      groups.character.push(card)
      continue
    }
    const parsed = parseLibraryRole(card.asset.role)
    if (parsed.entityType === 'character') groups.character.push(card)
    else if (parsed.entityType === 'scene') groups.scene.push(card)
    else if (parsed.entityType === 'prop') groups.prop.push(card)
    else groups.other.push(card)
  }
  const sortKey = (card: LibraryCard) => {
    if (card.kind === 'character') return String(card.title || '').trim()
    return String(card.asset?.meta?.entity_name || card.asset?.role || '').trim()
  }
  ;(Object.keys(groups) as LibraryCardGroupKey[]).forEach((groupKey) => {
    groups[groupKey].sort((a, b) => sortKey(a).localeCompare(sortKey(b), 'zh-CN'))
  })
  return groups
}

export function buildCharacterNameById(
  assets: LibraryAsset[],
  spec?: Record<string, any>,
): Map<number, string> {
  const map = new Map<number, string>()
  const remember = (entityIdRaw: unknown, nameRaw: unknown) => {
    const entityId = Number.parseInt(String(entityIdRaw ?? ''), 10)
    const name = String(nameRaw || '').trim()
    if (!Number.isFinite(entityId) || entityId <= 0 || isPlaceholderEntityName(name)) return
    if (!map.has(entityId)) map.set(entityId, name)
  }

  const specCharacters = Array.isArray(spec?.characters) ? (spec!.characters as any[]) : []
  for (const item of specCharacters) {
    remember(item?.entity_id, item?.name)
  }
  for (const asset of assets) {
    const parsed = parseLibraryRole(String(asset?.role || '').trim())
    if (parsed.entityType !== 'character' || !parsed.entityId) continue
    remember(parsed.entityId, asset?.meta?.entity_name)
  }
  return map
}

export function getLibraryAssetDisplayTitle(
  asset: LibraryAsset,
  characterNameById: Map<number, string>,
): string {
  const parsed = parseLibraryRole(asset.role)
  const rawEntityName = String(asset?.meta?.entity_name || '').trim()
  const fallbackCharacterName =
    parsed.entityType === 'character' && parsed.entityId
      ? characterNameById.get(parsed.entityId) || `角色#${parsed.entityId}`
      : ''
  const normalizedEntityName = isPlaceholderEntityName(rawEntityName) ? fallbackCharacterName : rawEntityName

  if (parsed.entityType === 'character' && parsed.entityId) {
    if (normalizedEntityName && parsed.view) {
      return `${normalizedEntityName} ${characterViewLabel(parsed.view)}`
    }
    return normalizedEntityName || assetTitle(asset)
  }

  return assetTitle(asset)
}
