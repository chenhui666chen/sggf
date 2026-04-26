import type { UserAssetRecord } from '@/services/api'

import {
  buildToggleArchivedUserAssetCommand,
  buildToggleFavoriteUserAssetCommand,
  getUserAssetActionKey,
  type UserAssetActionCommand,
} from './userAssetListPresentation'

type UserAssetCardControllerReadable = Pick<
  UserAssetRecord,
  'id' | 'is_favorite' | 'archived_at' | 'created_at'
>

type BuildUserAssetCardControllerOptions = {
  assetActionKey?: string | null
  selectedAssetIdSet?: ReadonlySet<number>
}

export type UserAssetCardController = {
  cardKey: string
  createdAtLabel: string
  isSelected: boolean
  isSubmitting: boolean
  favoriteCommand: UserAssetActionCommand
  archiveCommand: UserAssetActionCommand
}

export function formatUserAssetCardDateTime(value?: string | null): string {
  if (!value) return '暂无时间'
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp) || timestamp <= 0) return '暂无时间'
  return new Date(value).toLocaleString('zh-CN')
}

export function buildUserAssetCardController(
  asset: UserAssetCardControllerReadable,
  options: BuildUserAssetCardControllerOptions = {},
): UserAssetCardController {
  const selectedAssetIdSet = options.selectedAssetIdSet || new Set<number>()
  const actionKey = getUserAssetActionKey(asset.id)

  return {
    cardKey: `user-asset-${asset.id}`,
    createdAtLabel: formatUserAssetCardDateTime(asset.created_at),
    isSelected: selectedAssetIdSet.has(asset.id),
    isSubmitting: options.assetActionKey === actionKey,
    favoriteCommand: buildToggleFavoriteUserAssetCommand(asset),
    archiveCommand: buildToggleArchivedUserAssetCommand(asset),
  }
}
