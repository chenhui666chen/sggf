import type {
  DreamweaverAssetPlanItem,
  DreamweaverLibraryPlanItem,
  LibraryAsset,
  LibraryDisplayItem,
  LibraryPayload,
} from '@/types/dreamweaver'
import type { TFunction } from 'i18next'
import {
  CHARACTER_VIEW_ORDER,
  CHARACTER_VIEW_RANK,
  characterViewLabel,
  parseLibraryRole,
} from '@/utils/dreamweaverLibraryRole'
import { isPlaceholderEntityName, libraryAssetToCssAspectRatio } from '@/utils/dreamweaver'
import { resolveLibraryAssetImageState } from '@/utils/dreamweaverLibraryAssetState'
import { asObject } from './runPageDataTransforms'

export type LibraryGroupSummary = {
  total: number
  generated: number
  processing: number
  planned: number
  approved: number
  pendingReview: number
}

export type CharacterLibraryBucket = {
  bucketKey: string
  entityId: number
  name: string
  items: LibraryDisplayItem[]
}

export type LibraryDisplayGroup = {
  key: LibraryDisplayItem['group']
  label: string
  items: LibraryDisplayItem[]
  summary: LibraryGroupSummary
}

export function buildCharacterLibraryBuckets(items: LibraryDisplayItem[], t?: TFunction): CharacterLibraryBucket[] {
  const viewSuffixes = CHARACTER_VIEW_ORDER.map((view) => characterViewLabel(view)).sort((a, b) => b.length - a.length)
  const stripViewSuffix = (value: string) => {
    const text = String(value || '').trim()
    for (const suffix of viewSuffixes) {
      const candidate = ` ${suffix}`
      if (text.endsWith(candidate)) return text.slice(0, -candidate.length).trim()
    }
    return text
  }

  const buckets = new Map<string, CharacterLibraryBucket>()
  for (const item of items) {
    const parsed = parseLibraryRole(item.role)
    const parsedEntityId = typeof parsed.entityId === 'number' ? parsed.entityId : 0
    const entityId = parsed.entityType === 'character' && parsedEntityId > 0 ? parsedEntityId : 0
    const fallbackName = entityId > 0
      ? (t ? t('dreamweaverRun.libraryCharacterFallback', { id: entityId }) : `角色#${entityId}`)
      : (t ? t('dreamweaverRun.libraryUnnamedCharacter') : '未命名角色')
    const strippedTitle = stripViewSuffix(item.title)
    const baseName = isPlaceholderEntityName(strippedTitle) || strippedTitle === item.role ? fallbackName : strippedTitle
    const bucketKey = entityId > 0 ? `character:${entityId}` : `character:${baseName}`
    if (!buckets.has(bucketKey)) {
      buckets.set(bucketKey, { bucketKey, entityId, name: baseName, items: [] })
    }
    buckets.get(bucketKey)!.items.push(item)
  }

  return Array.from(buckets.values())
    .map((bucket) => ({
      ...bucket,
      items: [...bucket.items].sort((a, b) => {
        if (a.viewRank !== b.viewRank) return a.viewRank - b.viewRank
        return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
      }),
    }))
    .sort((a, b) => {
      if (a.entityId > 0 && b.entityId > 0) return a.entityId - b.entityId
      if (a.entityId > 0) return -1
      if (b.entityId > 0) return 1
      return a.name.localeCompare(b.name, 'zh-CN')
    })
}

export type LibraryDisplayCardState = {
  asset: LibraryAsset | null
  hasRenderableImage: boolean
  missing: boolean
  placeholder: boolean
  approved: boolean
  safetyBlocked: boolean
  safetyError: string | null
  statusLabel: string
  statusColor: 'default' | 'success' | 'info' | 'error' | 'warning'
  preview: string
  placeholderText: string
  previewLoading: boolean
  previewError: string | null
  canGenerate: boolean
  roleLabel: string
  backgroundColor: string
  placeholderColor: string
  placeholderBackgroundImage: string
  hasAsset: boolean
}

export function resolveLibraryDisplayCardState(
  item: LibraryDisplayItem,
  missingRoleSet: Set<string>,
  libraryPreviewLoading: Record<number, boolean>,
  libraryPreviewErrors: Record<number, string>,
  t?: TFunction,
): LibraryDisplayCardState {
  const asset = item.asset ?? null
  const imageState = item.imageState || resolveLibraryAssetImageState(asset || null, { missingRoleSet })
  const hasRenderableImage = Boolean(item.hasRenderableImage ?? imageState.hasRenderableImage)
  const missing = Boolean(item.missing || imageState.markedMissing)
  const placeholder = Boolean(item.placeholder || (asset && imageState.placeholder && !missing && !imageState.safetyBlocked))
  const approved = hasRenderableImage && (asset ? Boolean(asset.meta?.approved) : Boolean(item.approved))
  const safetyBlocked = Boolean(item.safety_blocked || imageState.safetyBlocked || asset?.meta?.safety_blocked)
  const safetyError = item.safety_error || (asset?.meta?.safety_error as string | undefined) || null
  const statusLabel = missing
    ? (t ? t('dreamweaverRun.libraryStatusMissing') : '缺失')
    : safetyBlocked
      ? (t ? t('dreamweaverRun.libraryStatusSafetyBlocked') : '安全拦截')
      : placeholder
        ? (t ? t('dreamweaverRun.libraryStatusPlaceholder') : '占位')
        : asset
          ? approved
            ? (t ? t('dreamweaverRun.libraryStatusApproved') : '已通过')
            : (t ? t('dreamweaverRun.libraryStatusPendingReview') : '待审核')
          : item.status === 'done'
            ? (t ? t('dreamweaverRun.libraryStatusGenerated') : '已生成')
            : item.status === 'planned'
              ? (t ? t('dreamweaverRun.libraryStatusPlanned') : '待生成')
              : (t ? t('dreamweaverRun.libraryStatusProcessing') : '生成中')
  const statusColor: 'default' | 'success' | 'info' | 'error' | 'warning' = missing
    ? 'error'
    : safetyBlocked
      ? 'error'
      : placeholder
        ? 'warning'
        : asset
          ? approved
            ? 'success'
            : 'default'
          : item.status === 'done'
            ? 'success'
            : item.status === 'planned'
              ? 'default'
              : 'info'
  const preview = asset && hasRenderableImage ? item.preview : ''
  const placeholderText = missing
    ? (t ? t('dreamweaverRun.libraryPlaceholderMissing') : '素材缺失')
    : safetyBlocked
      ? (t ? t('dreamweaverRun.libraryStatusSafetyBlocked') : '安全拦截')
      : placeholder
        ? (t ? t('dreamweaverRun.libraryPlaceholderImage') : '占位图')
        : asset
          ? (t ? t('dreamweaverRun.libraryPlaceholderLoading') : '待加载预览')
          : item.status === 'done'
            ? (t ? t('dreamweaverRun.libraryPlaceholderGeneratedAwaiting') : '已生成，等待入库')
            : item.status === 'planned'
              ? (t ? t('dreamweaverRun.libraryStatusPlanned') : '待生成')
              : (t ? t('dreamweaverRun.libraryStatusProcessing') : '生成中')
  const previewLoading = asset ? Boolean(libraryPreviewLoading[asset.id]) : false
  const previewError = asset ? libraryPreviewErrors[asset.id] : null
  const canGenerate = !asset && (missing || item.status === 'done')
  const roleLabel = item.group === 'other' && item.role ? `role: ${item.role}` : ''
  const backgroundColor = safetyBlocked || missing ? '#fff5f5' : placeholder ? '#fffaf0' : '#f5f5f5' // sg-color-fixed: 库卡占位状态底（数据纹理色）
  const placeholderColor = safetyBlocked || missing ? 'error.main' : placeholder ? 'warning.main' : 'text.secondary'
  const placeholderBackgroundImage = safetyBlocked || missing
    ? 'repeating-linear-gradient(45deg, rgba(211,47,47,0.05) 0, rgba(211,47,47,0.05) 8px, rgba(211,47,47,0.1) 8px, rgba(211,47,47,0.1) 16px)' // sg-color-fixed: 安全拦截斜纹纹理（数据纹理色）
    : placeholder
      ? 'repeating-linear-gradient(45deg, rgba(245,124,0,0.05) 0, rgba(245,124,0,0.05) 8px, rgba(245,124,0,0.1) 8px, rgba(245,124,0,0.1) 16px)' // sg-color-fixed: 占位斜纹纹理（数据纹理色）
      : 'repeating-linear-gradient(45deg, rgba(0,0,0,0.02) 0, rgba(0,0,0,0.02) 8px, rgba(0,0,0,0.04) 8px, rgba(0,0,0,0.04) 16px)' // sg-color-fixed: 常规斜纹纹理（数据纹理色）
  return {
    asset,
    hasRenderableImage,
    missing,
    placeholder,
    approved,
    safetyBlocked,
    safetyError,
    statusLabel,
    statusColor,
    preview,
    placeholderText,
    previewLoading,
    previewError,
    canGenerate,
    roleLabel,
    backgroundColor,
    placeholderColor,
    placeholderBackgroundImage,
    hasAsset: Boolean(asset),
  }
}

export function normalizeAssetPlanItems(items: unknown): DreamweaverAssetPlanItem[] {
  if (!Array.isArray(items)) return []
  return items
    .map((raw) => {
      const item = asObject(raw)
      if (!item) return null
      const id = String(item.id || '').trim()
      if (!id) return null
      const kindRaw = String(item.kind || '').trim().toLowerCase()
      const roleRaw = String(item.role || '').trim()
      const statusRaw = String(item.status || '').trim().toLowerCase()
      const kind = kindRaw === 'video' ? 'video' : kindRaw === 'image' ? 'image' : roleRaw === 'video_clip' || roleRaw === 'merged_video' ? 'video' : 'image'
      const status = statusRaw === 'done' ? 'done' : statusRaw === 'processing' ? 'processing' : 'planned'
      const uri = typeof item.uri === 'string' ? String(item.uri || '').trim() : ''
      const camIdx = typeof item.cam_idx === 'number' ? item.cam_idx : null
      return {
        id,
        shot_id: item.shot_id != null ? String(item.shot_id) : null,
        scene_id: item.scene_id != null ? String(item.scene_id) : null,
        cam_idx: camIdx,
        role: roleRaw || null,
        kind,
        label: typeof item.label === 'string' ? String(item.label || '') : id,
        status,
        optional: Boolean(item.optional),
        uri: uri || null,
      } as DreamweaverAssetPlanItem
    })
    .filter(Boolean) as DreamweaverAssetPlanItem[]
}

export function normalizeLibraryPlanItems(items: unknown): DreamweaverLibraryPlanItem[] {
  if (!Array.isArray(items)) return []
  return items
    .map((raw) => {
      const item = asObject(raw)
      if (!item) return null
      const role = String(item.role || '').trim()
      const id = String(item.id || role || '').trim()
      if (!id || !role) return null
      const statusRaw = String(item.status || '').trim().toLowerCase()
      const status = statusRaw === 'done' ? 'done' : statusRaw === 'planned' ? 'planned' : 'processing'
      const entityType = item.entity_type != null ? String(item.entity_type) : null
      const entityId = typeof item.entity_id === 'number' ? item.entity_id : Number(item.entity_id || 0) || null
      const entityName = typeof item.entity_name === 'string' ? String(item.entity_name || '').trim() : null
      const label = typeof item.label === 'string' ? String(item.label || '').trim() : ''
      const view = typeof item.view === 'string' ? String(item.view || '').trim() : null
      const uri = typeof item.uri === 'string' ? String(item.uri || '').trim() : ''
      const assetId = typeof item.asset_id === 'number' ? item.asset_id : Number(item.asset_id || 0) || null
      const approved = typeof item.approved === 'boolean' ? Boolean(item.approved) : null
      return {
        id,
        role,
        entity_type: entityType,
        entity_id: entityId,
        entity_name: entityName,
        label: label || role,
        view,
        status,
        kind: 'image',
        uri: uri || null,
        asset_id: assetId,
        approved,
      } as DreamweaverLibraryPlanItem
    })
    .filter(Boolean) as DreamweaverLibraryPlanItem[]
}

export type ComputeLibraryDisplayItemsParams = {
  library: LibraryPayload | null
  libraryPlanItems: DreamweaverLibraryPlanItem[]
  libraryPreviews: Record<string, string>
  libraryPreviewAspectRatio: string
  missingRoleSet: Set<string>
}

export function computeLibraryDisplayItems(params: ComputeLibraryDisplayItemsParams, t?: TFunction): LibraryDisplayItem[] {
  const { library, libraryPlanItems, libraryPreviews, libraryPreviewAspectRatio, missingRoleSet } = params
  const assets = Array.isArray(library?.assets) ? (library?.assets as LibraryAsset[]) : []
  const normalizedMissingRoles = Array.from(missingRoleSet.values())
  const characterNameById = new Map<number, string>()
  const rememberCharacterName = (entityIdRaw: unknown, nameRaw: unknown) => {
    const entityId = Number.parseInt(String(entityIdRaw ?? ''), 10)
    const name = String(nameRaw || '').trim()
    if (!Number.isFinite(entityId) || entityId <= 0 || isPlaceholderEntityName(name)) return
    const prev = characterNameById.get(entityId)
    if (!prev || isPlaceholderEntityName(prev)) {
      characterNameById.set(entityId, name)
    }
  }
  const specCharacters = Array.isArray(library?.spec?.characters) ? library.spec.characters : []
  for (const rawItem of specCharacters) {
    const item = asObject(rawItem)
    if (!item) continue
    rememberCharacterName(item.entity_id, item.name)
  }
  for (const plan of libraryPlanItems) {
    if (String(plan?.entity_type || '').trim().toLowerCase() !== 'character') continue
    rememberCharacterName(plan?.entity_id, plan?.entity_name)
  }
  const assetsByRole = new Map<string, LibraryAsset>()
  for (const asset of assets) {
    const role = String(asset?.role || '').trim()
    if (!role) continue
    assetsByRole.set(role, asset)
    const parsed = parseLibraryRole(role)
    if (parsed.entityType === 'character' && parsed.entityId) {
      rememberCharacterName(parsed.entityId, asset?.meta?.entity_name)
    }
  }

  const normalizeRole = (rawRole: string) => {
    const role = String(rawRole || '').trim()
    const parsed = parseLibraryRole(role)
    let group: LibraryDisplayItem['group'] = 'other'
    let view: LibraryDisplayItem['view'] = null
    if (parsed.entityType === 'character') {
      group = 'character'
      view = parsed.view || null
    } else if (parsed.entityType === 'scene') {
      group = 'scene'
    } else if (parsed.entityType === 'prop') {
      group = 'prop'
    }
    const viewRank = view ? CHARACTER_VIEW_RANK[view] : 99
    const viewLabel = view ? characterViewLabel(view) : ''
    return { role, group, view, viewRank, viewLabel }
  }

  const formatTitle = (rawTitle: string, role: string, viewLabel: string) => {
    const parsed = parseLibraryRole(role)
    const raw = String(rawTitle || '').trim()
    let base = raw || role
    if (parsed.entityType === 'character' && parsed.entityId) {
      const mapped = characterNameById.get(parsed.entityId) || ''
      const fallbackCharacterName = mapped || (t ? t('dreamweaverRun.libraryCharacterFallback', { id: parsed.entityId }) : `角色#${parsed.entityId}`)
      if (raw === role || isPlaceholderEntityName(raw)) {
        base = fallbackCharacterName
      }
      if (!String(base || '').trim()) base = fallbackCharacterName
    }
    if (viewLabel && !base.includes(viewLabel)) return `${base} ${viewLabel}`
    return base
  }

  const makeAssetItem = (asset: LibraryAsset, key: string): LibraryDisplayItem => {
    const { role, group, view, viewRank, viewLabel } = normalizeRole(String(asset?.role || '').trim() || key)
    const rawTitle = String(asset?.meta?.entity_name || asset?.role || '').trim()
    const title = formatTitle(rawTitle, role, viewLabel)
    const imageState = resolveLibraryAssetImageState(asset, { missingRoleSet })
    const hasRenderableImage = imageState.hasRenderableImage
    const preview = hasRenderableImage ? libraryPreviews[asset.id] || '' : ''
    const aspectRatio = libraryAssetToCssAspectRatio(asset, libraryPreviewAspectRatio)
    const approved = hasRenderableImage && Boolean(asset.meta?.approved)
    const safety_blocked = Boolean(imageState.safetyBlocked || asset.meta?.safety_blocked)
    const safety_error = typeof asset.meta?.safety_error === 'string' ? asset.meta.safety_error : null
    const placeholder = Boolean(imageState.placeholder && !imageState.markedMissing && !imageState.safetyBlocked)
    return {
      key,
      role,
      title,
      preview,
      aspectRatio,
      approved,
      status: 'done' as const,
      group,
      view,
      viewRank,
      asset,
      missing: imageState.markedMissing,
      placeholder,
      hasRenderableImage,
      imageState,
      safety_blocked,
      safety_error,
    }
  }

  const items: LibraryDisplayItem[] = []
  const usedRoles = new Set<string>()

  const pushMissingItem = (rawRole: string) => {
    const role = String(rawRole || '').trim()
    if (!role || usedRoles.has(role)) return
    const { group, view, viewRank, viewLabel } = normalizeRole(role)
    const title = formatTitle(role, role, viewLabel)
    items.push({
      key: `missing:${role}`,
      role,
      title,
      preview: '',
      aspectRatio: libraryPreviewAspectRatio,
      approved: false,
      status: 'planned',
      group,
      view,
      viewRank,
      missing: true,
      placeholder: false,
      hasRenderableImage: false,
      imageState: null,
    })
    usedRoles.add(role)
  }

  if (libraryPlanItems.length) {
    for (const plan of libraryPlanItems) {
      const role = String(plan.role || '').trim()
      if (!role) continue
      usedRoles.add(role)
      const asset = assetsByRole.get(role)
      if (asset) {
        items.push(makeAssetItem(asset, `plan:${role}`))
        continue
      }
      const { group, view, viewRank, viewLabel } = normalizeRole(role)
      const rawTitle = String(plan.label || plan.entity_name || role).trim()
      const title = formatTitle(rawTitle, role, viewLabel)
      items.push({
        key: `plan:${role}`,
        role,
        title,
        preview: '',
        aspectRatio: libraryPreviewAspectRatio,
        approved: Boolean(plan.approved),
        status: plan.status === 'done' ? 'done' : plan.status === 'planned' ? 'planned' : 'processing',
        group,
        view,
        viewRank,
        missing: !asset && missingRoleSet.has(role),
        placeholder: false,
        hasRenderableImage: false,
        imageState: null,
      })
    }
    for (const asset of assets) {
      const role = String(asset?.role || '').trim()
      if (!role || usedRoles.has(role)) continue
      usedRoles.add(role)
      items.push(makeAssetItem(asset, `asset:${asset.id}`))
    }
    for (const role of normalizedMissingRoles) {
      pushMissingItem(role)
    }
    return items
  }

  for (const asset of assets) {
    const role = String(asset?.role || '').trim()
    if (role) usedRoles.add(role)
    items.push(makeAssetItem(asset, `asset:${asset.id}`))
  }
  for (const role of normalizedMissingRoles) {
    pushMissingItem(role)
  }
  return items
}

export function computeLibrarySummary(items: LibraryDisplayItem[]): LibraryGroupSummary {
  let generated = 0
  let processing = 0
  let planned = 0
  let approved = 0
  let pendingReview = 0
  for (const item of items) {
    if (item.hasRenderableImage) {
      generated += 1
    } else if (!item.asset && item.status === 'processing') {
      processing += 1
    } else {
      planned += 1
    }
    if (item.asset && item.hasRenderableImage) {
      if (item.approved) approved += 1
      else pendingReview += 1
    }
  }
  return { total: items.length, generated, processing, planned, approved, pendingReview }
}

export function computeLibraryGroups(items: LibraryDisplayItem[], t?: TFunction): LibraryDisplayGroup[] {
  const order: Array<LibraryDisplayItem['group']> = ['character', 'scene', 'prop', 'other']
  const labels: Record<LibraryDisplayItem['group'], string> = {
    character: t ? t('dreamweaverRun.libraryGroupCharacter') : '角色',
    scene: t ? t('dreamweaverRun.libraryGroupScene') : '场景',
    prop: t ? t('dreamweaverRun.libraryGroupProp') : '道具',
    other: t ? t('dreamweaverRun.libraryGroupOther') : '其他',
  }
  const groups = new Map<LibraryDisplayItem['group'], LibraryDisplayItem[]>()
  for (const item of items) {
    const key = item.group || 'other'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(item)
  }
  const result: LibraryDisplayGroup[] = []
  for (const key of order) {
    const groupItems = groups.get(key) || []
    if (!groupItems.length) continue
    const viewSuffixes = CHARACTER_VIEW_ORDER.map((view) => characterViewLabel(view)).sort((a, b) => b.length - a.length)
    const stripView = (value: string) => {
      const text = String(value || '').trim()
      for (const suffix of viewSuffixes) {
        const candidate = ` ${suffix}`
        if (text.endsWith(candidate)) return text.slice(0, -candidate.length)
      }
      return text
    }
    const sorted = [...groupItems].sort((a, b) => {
      const nameA = stripView(String(a.title || ''))
      const nameB = stripView(String(b.title || ''))
      if (nameA !== nameB) return nameA.localeCompare(nameB, 'zh-CN')
      if (a.viewRank !== b.viewRank) return a.viewRank - b.viewRank
      return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
    })
    const summary: LibraryGroupSummary = {
      total: sorted.length,
      generated: sorted.filter((i) => i.hasRenderableImage).length,
      processing: sorted.filter((i) => !i.asset && i.status === 'processing').length,
      planned: sorted.filter((i) => !i.hasRenderableImage && (i.asset || i.status === 'planned' || i.status === 'done')).length,
      approved: sorted.filter((i) => i.asset && i.hasRenderableImage && i.approved).length,
      pendingReview: sorted.filter((i) => i.asset && i.hasRenderableImage && !i.approved).length,
    }
    result.push({ key, label: labels[key], items: sorted, summary })
  }
  return result
}

export function buildMissingRoleSet(library: { review?: { missing_roles?: unknown } | null } | null): Set<string> {
  const missingRoles = Array.isArray(library?.review?.missing_roles) ? (library!.review!.missing_roles as string[]) : []
  return new Set(missingRoles.map((role) => String(role || '').trim()).filter(Boolean))
}

export function buildLibraryAssetsByRole(library: { assets?: unknown } | null): Map<string, LibraryAsset> {
  const map = new Map<string, LibraryAsset>()
  const assets = Array.isArray(library?.assets) ? (library!.assets as LibraryAsset[]) : []
  for (const asset of assets) {
    const role = String(asset?.role || '').trim()
    if (!role) continue
    map.set(role, asset)
  }
  return map
}

export function extractMissingRoleSet(data: { review?: { missing_roles?: unknown } | null } | null): Set<string> {
  const missingRoles = Array.isArray(data?.review?.missing_roles) ? (data.review.missing_roles as string[]) : []
  return new Set(missingRoles.map((role) => String(role || '').trim()).filter(Boolean))
}
