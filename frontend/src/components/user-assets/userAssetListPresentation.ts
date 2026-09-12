import type { TFunction } from 'i18next'

import {
  getUserAssetSourceInfo,
  getUserAssetSourceModule,
  type UserAssetProjectTitleMap,
} from '@/contracts/userAssetSourceReaders'
import type {
  UserAssetRecord,
  UserAssetRecordUpdatePayload,
} from '@/services/api'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

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
  t?: TFunction,
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
          }, undefined, t).label,
        ] as const)),
    ).entries(),
  )
    .sort((left, right) => left[1].localeCompare(right[1], 'zh-CN'))
    .map(([value, label]) => ({ value, label }))
}

export function buildUserAssetSourceOptions(
  assets: UserAssetRecord[],
  projectTitleMap?: UserAssetProjectTitleMap,
  t?: TFunction,
): UserAssetSourceOption[] {
  const preferredSourceLabels = new Map(
    assets
      .map((asset) => [getUserAssetSourceModule(asset), getUserAssetSourceInfo(asset, projectTitleMap, t).label] as const)
      .filter(([value]) => Boolean(value)),
  )

  return buildUserAssetSourceOptionsFromSourceModules(Array.from(preferredSourceLabels.keys()), t).map((option) => ({
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
  t?: TFunction,
): UserAssetActionCommand {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    actionKey: getUserAssetActionKey(asset.id),
    payload: { is_favorite: !asset.is_favorite },
    successText: asset.is_favorite ? translate('userAsset.command.unFavoriteSuccess') : translate('userAsset.command.favoriteSuccess'),
  }
}

export function buildToggleArchivedUserAssetCommand(
  asset: Pick<UserAssetRecord, 'id' | 'archived_at'>,
  t?: TFunction,
): UserAssetActionCommand {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    actionKey: getUserAssetActionKey(asset.id),
    payload: { archived: !asset.archived_at },
    successText: asset.archived_at ? translate('userAsset.command.activateSuccess') : translate('userAsset.command.archiveSuccess'),
  }
}

export function buildFavoriteBatchUserAssetCommand(t?: TFunction): UserAssetRemoteBatchActionCommand {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    kind: 'remote_update',
    label: translate('userAsset.command.favorite'),
    payload: { is_favorite: true },
    successText: translate('userAsset.command.favoriteBatchSuccess'),
  }
}

export function buildArchiveBatchUserAssetCommand(t?: TFunction): UserAssetRemoteBatchActionCommand {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    kind: 'remote_update',
    label: translate('userAsset.command.archive'),
    payload: { archived: true },
    successText: translate('userAsset.command.archiveBatchSuccess'),
  }
}

export function buildActivateBatchUserAssetCommand(t?: TFunction): UserAssetRemoteBatchActionCommand {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    kind: 'remote_update',
    label: translate('userAsset.command.activate'),
    payload: { archived: false },
    successText: translate('userAsset.command.activateBatchSuccess'),
  }
}

export function buildClearLocalCopyBatchUserAssetCommand(t?: TFunction): UserAssetLocalBatchActionCommand {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    kind: 'clear_local_copy',
    label: translate('userAsset.command.clearLocalCopy'),
    successText: translate('userAsset.command.clearLocalCopyBatchSuccess'),
  }
}

export function buildRestoreLocalCopyBatchUserAssetCommand(t?: TFunction): UserAssetRestoreLocalBatchActionCommand {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    kind: 'restore_local_copy',
    label: translate('userAsset.command.restoreLocalCopy'),
    successText: translate('userAsset.command.restoreLocalCopyBatchSuccess'),
  }
}
