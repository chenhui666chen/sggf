import type { ChipProps } from '@mui/material'
import type { TFunction } from 'i18next'

import type { UserAssetSourceInfo } from '@/contracts/userAssetSourceReaders'
import type { UserAssetRecord } from '@/services/api'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export type UserAssetCardChipSpec = {
  key: string
  label: string
  color?: ChipProps['color']
  variant?: ChipProps['variant']
}

export type UserAssetCardActionSpec = {
  label: string
  path?: string | null
}

export type UserAssetCardPresentation = {
  headerChips: UserAssetCardChipSpec[]
  detailChips: UserAssetCardChipSpec[]
  description: string
  sourceSummary: string
  selectionLabel: string
  createdAtLabel: string
  sourceAction?: UserAssetCardActionSpec | null
  restoreLocalAction?: UserAssetCardActionSpec | null
  clearLocalAction?: UserAssetCardActionSpec | null
  editAction: UserAssetCardActionSpec
  favoriteAction: UserAssetCardActionSpec
  archiveAction: UserAssetCardActionSpec
}

type BuildUserAssetCardPresentationOptions = {
  createdAtLabel: string
  hasLocalObjectUrl?: boolean
}

export function buildUserAssetCardPresentation(
  asset: Pick<
    UserAssetRecord,
    | 'id'
    | 'asset_kind'
    | 'asset_class'
    | 'asset_uuid'
    | 'storage_mode'
    | 'description'
    | 'is_favorite'
    | 'archived_at'
    | 'tags'
  >,
  sourceInfo: UserAssetSourceInfo,
  options: BuildUserAssetCardPresentationOptions,
  t?: TFunction,
): UserAssetCardPresentation {
  const translate = t ?? DEFAULT_TRANSLATE
  const headerChips: UserAssetCardChipSpec[] = [
    {
      key: `asset-kind-${asset.id}`,
      label: asset.asset_kind,
    },
    {
      key: `asset-class-${asset.id}`,
      label: asset.asset_class === 'deliverable' ? translate('userAsset.card.deliverable') : translate('userAsset.card.reusable'),
      color: asset.asset_class === 'deliverable' ? 'warning' : 'secondary',
    },
    {
      key: `asset-source-${asset.id}`,
      label: translate('userAsset.card.sourcePrefix', { source: sourceInfo.label }),
      variant: 'outlined',
    },
  ]

  if (asset.is_favorite) {
    headerChips.push({
      key: `asset-favorite-${asset.id}`,
      label: translate('userAsset.card.favorite'),
      color: 'primary',
    })
  }

  if (asset.archived_at) {
    headerChips.push({
      key: `asset-archived-${asset.id}`,
      label: translate('userAsset.card.archived'),
      variant: 'outlined',
    })
  }

  const detailChips: UserAssetCardChipSpec[] = []
  if (sourceInfo.projectLabel) {
    detailChips.push({
      key: `asset-project-${asset.id}`,
      label: sourceInfo.projectLabel,
      variant: 'outlined',
    })
  }
  if (sourceInfo.traceLabel) {
    detailChips.push({
      key: `asset-trace-${asset.id}`,
      label: sourceInfo.traceLabel,
      variant: 'outlined',
    })
  }
  asset.tags.slice(0, 3).forEach((tag) => {
    detailChips.push({
      key: `asset-tag-${asset.id}-${tag}`,
      label: tag,
      variant: 'outlined',
    })
  })

  const showRestoreLocalAction =
    asset.storage_mode === 'local_mirror'
    && asset.asset_uuid.trim()
    && !options.hasLocalObjectUrl

  if (showRestoreLocalAction) {
    detailChips.push({
      key: `asset-local-restore-${asset.id}`,
      label: translate('userAsset.card.localRestorePending'),
      color: 'warning',
    })
  }

  return {
    headerChips,
    detailChips,
    description: asset.description?.trim() || translate('userAsset.card.noDescription'),
    sourceSummary: sourceInfo.summary,
    selectionLabel: translate('userAsset.card.selection'),
    createdAtLabel: translate('userAsset.card.createdAt', { time: options.createdAtLabel }),
    sourceAction: sourceInfo.backPath
      ? {
          label: sourceInfo.backLabel || translate('userAsset.common.viewSource'),
          path: sourceInfo.backPath,
        }
      : null,
    restoreLocalAction: showRestoreLocalAction
      ? {
          label: translate('userAsset.card.restoreLocal'),
        }
      : null,
    clearLocalAction: asset.storage_mode === 'local_mirror' && asset.asset_uuid.trim()
      ? {
          label: translate('userAsset.card.clearLocal'),
        }
      : null,
    editAction: {
      label: translate('userAsset.card.edit'),
    },
    favoriteAction: {
      label: asset.is_favorite ? translate('userAsset.card.unFavorite') : translate('userAsset.card.favoriteAction'),
    },
    archiveAction: {
      label: asset.archived_at ? translate('userAsset.card.restoreActive') : translate('userAsset.card.archive'),
    },
  }
}
