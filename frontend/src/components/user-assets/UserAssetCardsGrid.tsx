import {
  type UserAssetProjectTitleMap,
} from '@/contracts/userAssetSourceReaders'
import type {
  UserAssetRecord,
  UserAssetRecordUpdatePayload,
} from '@/services/api'

import type { UserAssetListSelectionState } from './userAssetListPresentation'
import UserAssetCard from './UserAssetCard'
import { buildUserAssetCardController } from './userAssetCardController'
import {
  buildUserAssetCardPreviewBridge,
  type UserAssetPreviewObjectUrlMaps,
} from './userAssetPreviewBridge'

export type UserAssetCardsGridProps = {
  assets: UserAssetRecord[]
  projectTitleMap?: UserAssetProjectTitleMap
  assetActionKey?: string | null
  assetBatchSubmitting?: boolean
  assetSelectionState: Pick<UserAssetListSelectionState, 'selectedAssetIdSet'>
  previewObjectUrls?: UserAssetPreviewObjectUrlMaps
  onToggleSelection: (assetId: number) => void
  onNavigateToPath: (path: string) => void
  onEditAsset: (asset: UserAssetRecord) => void
  onRestoreLocalCopyAsset: (asset: UserAssetRecord) => Promise<void> | void
  onClearLocalCopyAsset: (asset: UserAssetRecord) => Promise<void> | void
  onUpdateAsset: (
    assetId: number,
    payload: UserAssetRecordUpdatePayload,
    successText?: string,
  ) => Promise<void> | void
}

export default function UserAssetCardsGrid(props: UserAssetCardsGridProps) {
  const {
    assets,
    projectTitleMap,
    assetActionKey = null,
    assetBatchSubmitting = false,
    assetSelectionState,
    previewObjectUrls,
    onToggleSelection,
    onNavigateToPath,
    onEditAsset,
    onRestoreLocalCopyAsset,
    onClearLocalCopyAsset,
    onUpdateAsset,
  } = props

  return (
    <>
      {assets.map((asset) => {
        const controller = buildUserAssetCardController(asset, {
          assetActionKey,
          selectedAssetIdSet: assetSelectionState.selectedAssetIdSet,
        })
        const previewBridge = buildUserAssetCardPreviewBridge(asset, previewObjectUrls)

        return (
          <UserAssetCard
            key={controller.cardKey}
            asset={asset}
            projectTitleMap={projectTitleMap}
            localObjectUrl={previewBridge.localObjectUrl}
            protectedObjectUrl={previewBridge.protectedObjectUrl}
            createdAtLabel={controller.createdAtLabel}
            isSelected={controller.isSelected}
            batchDisabled={assetBatchSubmitting}
            isSubmitting={controller.isSubmitting}
            onToggleSelection={() => onToggleSelection(asset.id)}
            onNavigateToSource={onNavigateToPath}
            onEdit={() => onEditAsset(asset)}
            onRestoreLocalCopy={() => void onRestoreLocalCopyAsset(asset)}
            onClearLocalCopy={() => void onClearLocalCopyAsset(asset)}
            onToggleFavorite={() =>
              void onUpdateAsset(
                asset.id,
                controller.favoriteCommand.payload,
                controller.favoriteCommand.successText,
              )
            }
            onToggleArchived={() =>
              void onUpdateAsset(
                asset.id,
                controller.archiveCommand.payload,
                controller.archiveCommand.successText,
              )
            }
          />
        )
      })}
    </>
  )
}
