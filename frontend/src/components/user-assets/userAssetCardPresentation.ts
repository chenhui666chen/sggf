import type { ChipProps } from '@mui/material'

import type { UserAssetSourceInfo } from '@/contracts/userAssetSourceReaders'
import type { UserAssetRecord } from '@/services/api'

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
): UserAssetCardPresentation {
  const headerChips: UserAssetCardChipSpec[] = [
    {
      key: `asset-kind-${asset.id}`,
      label: asset.asset_kind,
    },
    {
      key: `asset-class-${asset.id}`,
      label: asset.asset_class === 'deliverable' ? '成品资产' : '可复用素材',
      color: asset.asset_class === 'deliverable' ? 'warning' : 'secondary',
    },
    {
      key: `asset-source-${asset.id}`,
      label: `来源：${sourceInfo.label}`,
      variant: 'outlined',
    },
  ]

  if (asset.is_favorite) {
    headerChips.push({
      key: `asset-favorite-${asset.id}`,
      label: '重点资产',
      color: 'primary',
    })
  }

  if (asset.archived_at) {
    headerChips.push({
      key: `asset-archived-${asset.id}`,
      label: '已归档',
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
      label: '本地副本待恢复',
      color: 'warning',
    })
  }

  return {
    headerChips,
    detailChips,
    description: asset.description?.trim() || '当前资产尚未补充说明，可以在用户中心内完善标题、描述和标签。',
    sourceSummary: sourceInfo.summary,
    selectionLabel: '纳入批量操作',
    createdAtLabel: `收录时间：${options.createdAtLabel}`,
    sourceAction: sourceInfo.backPath
      ? {
          label: sourceInfo.backLabel || '查看来源',
          path: sourceInfo.backPath,
        }
      : null,
    restoreLocalAction: showRestoreLocalAction
      ? {
          label: '重新收录到本地',
        }
      : null,
    clearLocalAction: asset.storage_mode === 'local_mirror' && asset.asset_uuid.trim()
      ? {
          label: '清理本地副本',
        }
      : null,
    editAction: {
      label: '编辑信息',
    },
    favoriteAction: {
      label: asset.is_favorite ? '取消重点' : '设为重点',
    },
    archiveAction: {
      label: asset.archived_at ? '恢复活跃' : '归档',
    },
  }
}
