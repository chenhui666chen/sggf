import type { TFunction } from 'i18next'
import type { AppLanguage } from '@/i18n'
import { formatDateTime } from '@/i18n/format'
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
  /** 卡片时间的显示语言，由调用组件从 useAppLanguage 取。 */
  locale?: AppLanguage
}

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export type UserAssetCardController = {
  cardKey: string
  createdAtLabel: string
  isSelected: boolean
  isSubmitting: boolean
  favoriteCommand: UserAssetActionCommand
  archiveCommand: UserAssetActionCommand
}

export function formatUserAssetCardDateTime(
  value?: string | null,
  locale?: AppLanguage,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (!value) return translate('userAsset.common.noTime')
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp) || timestamp <= 0) return translate('userAsset.common.noTime')
  return formatDateTime(value, { locale })
}

export function buildUserAssetCardController(
  asset: UserAssetCardControllerReadable,
  options: BuildUserAssetCardControllerOptions = {},
  t?: TFunction,
): UserAssetCardController {
  const selectedAssetIdSet = options.selectedAssetIdSet || new Set<number>()
  const actionKey = getUserAssetActionKey(asset.id)

  return {
    cardKey: `user-asset-${asset.id}`,
    createdAtLabel: formatUserAssetCardDateTime(asset.created_at, options.locale, t),
    isSelected: selectedAssetIdSet.has(asset.id),
    isSubmitting: options.assetActionKey === actionKey,
    favoriteCommand: buildToggleFavoriteUserAssetCommand(asset, t),
    archiveCommand: buildToggleArchivedUserAssetCommand(asset, t),
  }
}
