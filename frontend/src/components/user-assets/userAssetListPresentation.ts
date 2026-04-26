import {
  getUserAssetSourceInfo,
  getUserAssetSourceModule,
  type UserAssetProjectTitleMap,
} from '@/contracts/userAssetSourceReaders'
import type {
  UserAssetRecord,
  UserAssetRecordUpdatePayload,
} from '@/services/api'

export type UserAssetListViewFilter = 'all' | 'favorites' | 'deliverable' | 'reusable'
export type UserAssetListArchiveFilter = 'active' | 'archived' | 'all'

export type UserAssetSourceOption = {
  value: string
  label: string
}

export type UserAssetListFilters = {
  viewFilter: UserAssetListViewFilter
  kindFilter: string
  archiveFilter: UserAssetListArchiveFilter
  sourceFilter: string
  tagFilter: string
}

export type UserAssetActionCommand = {
  actionKey: string
  payload: UserAssetRecordUpdatePayload
  successText: string
}

export type UserAssetRemoteBatchActionCommand = {
  kind: 'remote_update'
  label: string
  payload: UserAssetRecordUpdatePayload
  successText: string
}

export type UserAssetLocalBatchActionCommand = {
  kind: 'clear_local_copy'
  label: string
  successText: string
}

export type UserAssetRestoreLocalBatchActionCommand = {
  kind: 'restore_local_copy'
  label: string
  successText: string
}

export type UserAssetBatchActionCommand =
  | UserAssetRemoteBatchActionCommand
  | UserAssetLocalBatchActionCommand
  | UserAssetRestoreLocalBatchActionCommand

export type UserAssetListSelectionState = {
  selectedAssetIds: number[]
  selectedAssetIdSet: Set<number>
  selectedAssets: UserAssetRecord[]
  selectedCount: number
  selectedLocalMirrorCount: number
  visibleCount: number
  hasSelection: boolean
  allVisibleSelected: boolean
}

function readTrimmedString(value: string | null | undefined): string {
  return String(value || '').trim()
}

function isLocalMirrorAsset(asset: Pick<UserAssetRecord, 'storage_mode' | 'asset_uuid'>): boolean {
  return asset.storage_mode === 'local_mirror' && Boolean(readTrimmedString(asset.asset_uuid))
}

export function getUserAssetActionKey(assetId: number): string {
  return `asset-${assetId}`
}

export function buildUserAssetKindOptionsFromValues(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => readTrimmedString(value)).filter(Boolean))).sort(
    (left, right) => left.localeCompare(right),
  )
}

export function buildUserAssetKindOptions(assets: UserAssetRecord[]): string[] {
  return buildUserAssetKindOptionsFromValues(assets.map((asset) => asset.asset_kind))
}

export function buildUserAssetTagOptionsFromValues(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => readTrimmedString(value)).filter(Boolean))).sort(
    (left, right) => left.localeCompare(right, 'zh-CN'),
  )
}

export function buildUserAssetTagOptions(assets: UserAssetRecord[]): string[] {
  return buildUserAssetTagOptionsFromValues(assets.flatMap((asset) => asset.tags))
}

export function buildUserAssetSourceOptionsFromSourceModules(
  sourceModules: string[],
): UserAssetSourceOption[] {
  return Array.from(
    new Map(
      sourceModules
        .map((value) => readTrimmedString(value).toLowerCase())
        .filter(Boolean)
        .map((value) => ([
          value,
          getUserAssetSourceInfo({
            source_module: value,
            project_id: null,
            source_payload_json: {},
            metadata_json: {},
          }).label,
        ] as const)),
    ).entries(),
  )
    .sort((left, right) => left[1].localeCompare(right[1], 'zh-CN'))
    .map(([value, label]) => ({ value, label }))
}

export function buildUserAssetSourceOptions(
  assets: UserAssetRecord[],
  projectTitleMap?: UserAssetProjectTitleMap,
): UserAssetSourceOption[] {
  const preferredSourceLabels = new Map(
    assets
      .map((asset) => [getUserAssetSourceModule(asset), getUserAssetSourceInfo(asset, projectTitleMap).label] as const)
      .filter(([value]) => Boolean(value)),
  )

  return buildUserAssetSourceOptionsFromSourceModules(Array.from(preferredSourceLabels.keys())).map((option) => ({
    value: option.value,
    label: preferredSourceLabels.get(option.value) || option.label,
  }))
}

export function filterUserAssets(
  assets: UserAssetRecord[],
  filters: UserAssetListFilters,
): UserAssetRecord[] {
  let nextAssets = [...assets]

  if (filters.archiveFilter === 'active') nextAssets = nextAssets.filter((asset) => !asset.archived_at)
  if (filters.archiveFilter === 'archived') nextAssets = nextAssets.filter((asset) => Boolean(asset.archived_at))
  if (filters.viewFilter === 'favorites') nextAssets = nextAssets.filter((asset) => asset.is_favorite)
  if (filters.viewFilter === 'deliverable') nextAssets = nextAssets.filter((asset) => asset.asset_class === 'deliverable')
  if (filters.viewFilter === 'reusable') nextAssets = nextAssets.filter((asset) => asset.asset_class !== 'deliverable')
  if (filters.kindFilter !== 'all') nextAssets = nextAssets.filter((asset) => asset.asset_kind === filters.kindFilter)
  if (filters.sourceFilter !== 'all') {
    nextAssets = nextAssets.filter((asset) => getUserAssetSourceModule(asset) === filters.sourceFilter)
  }
  if (filters.tagFilter !== 'all') nextAssets = nextAssets.filter((asset) => asset.tags.includes(filters.tagFilter))

  return nextAssets
}

export function buildUserAssetListSelectionState(
  visibleAssets: UserAssetRecord[],
  selectedAssetIds: number[],
): UserAssetListSelectionState {
  const selectedAssetIdSet = new Set(selectedAssetIds)
  const selectedAssets = visibleAssets.filter((asset) => selectedAssetIdSet.has(asset.id))
  const visibleCount = visibleAssets.length
  const selectedCount = selectedAssets.length
  const selectedLocalMirrorCount = selectedAssets.filter(isLocalMirrorAsset).length

  return {
    selectedAssetIds,
    selectedAssetIdSet,
    selectedAssets,
    selectedCount,
    selectedLocalMirrorCount,
    visibleCount,
    hasSelection: selectedCount > 0,
    allVisibleSelected:
      visibleCount > 0 && visibleAssets.every((asset) => selectedAssetIdSet.has(asset.id)),
  }
}

export function pruneUserAssetSelection(
  selectedAssetIds: number[],
  visibleAssets: Array<Pick<UserAssetRecord, 'id'>>,
): number[] {
  const visibleAssetIdSet = new Set(visibleAssets.map((asset) => asset.id))
  return selectedAssetIds.filter((assetId) => visibleAssetIdSet.has(assetId))
}

export function toggleUserAssetSelection(
  selectedAssetIds: number[],
  assetId: number,
): number[] {
  return selectedAssetIds.includes(assetId)
    ? selectedAssetIds.filter((currentId) => currentId !== assetId)
    : [...selectedAssetIds, assetId]
}

export function toggleSelectAllUserAssets(
  visibleAssets: Array<Pick<UserAssetRecord, 'id'>>,
  allVisibleSelected: boolean,
): number[] {
  if (allVisibleSelected) return []
  return visibleAssets.map((asset) => asset.id)
}

export function buildToggleFavoriteUserAssetCommand(
  asset: Pick<UserAssetRecord, 'id' | 'is_favorite'>,
): UserAssetActionCommand {
  return {
    actionKey: getUserAssetActionKey(asset.id),
    payload: { is_favorite: !asset.is_favorite },
    successText: asset.is_favorite ? '已取消重点资产' : '已设为重点资产',
  }
}

export function buildToggleArchivedUserAssetCommand(
  asset: Pick<UserAssetRecord, 'id' | 'archived_at'>,
): UserAssetActionCommand {
  return {
    actionKey: getUserAssetActionKey(asset.id),
    payload: { archived: !asset.archived_at },
    successText: asset.archived_at ? '已恢复为活跃资产' : '已归档资产',
  }
}

export function buildFavoriteBatchUserAssetCommand(): UserAssetRemoteBatchActionCommand {
  return {
    kind: 'remote_update',
    label: '设为重点',
    payload: { is_favorite: true },
    successText: '已批量设为重点',
  }
}

export function buildArchiveBatchUserAssetCommand(): UserAssetRemoteBatchActionCommand {
  return {
    kind: 'remote_update',
    label: '归档',
    payload: { archived: true },
    successText: '已批量归档',
  }
}

export function buildActivateBatchUserAssetCommand(): UserAssetRemoteBatchActionCommand {
  return {
    kind: 'remote_update',
    label: '恢复活跃',
    payload: { archived: false },
    successText: '已批量恢复为活跃',
  }
}

export function buildClearLocalCopyBatchUserAssetCommand(): UserAssetLocalBatchActionCommand {
  return {
    kind: 'clear_local_copy',
    label: '清理本地副本',
    successText: '已批量清理本地副本',
  }
}

export function buildRestoreLocalCopyBatchUserAssetCommand(): UserAssetRestoreLocalBatchActionCommand {
  return {
    kind: 'restore_local_copy',
    label: '重新收录到本地',
    successText: '已批量重新收录到本地',
  }
}
