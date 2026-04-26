import {
  didLocalAssetExternalDirectoryFallback,
  resolvePreferredLocalAssetStorageDriver,
  type PreferredLocalAssetStorageDriver,
} from './localAssetExternalDirectory'
import {
  saveLocalAsset,
  type LocalAssetVaultRecord,
  type SaveLocalAssetInput,
} from './localAssetVault'

export type SaveExplicitLocalUserAssetInput = Omit<SaveLocalAssetInput, 'preferredStorageDriver'>

export interface SaveExplicitLocalUserAssetResult {
  localAssetRecord: LocalAssetVaultRecord
  preferredStorageDriver: PreferredLocalAssetStorageDriver
  didFallbackToBrowserStorage: boolean
}

// 仅显式“收录到本地”的入口应走这层 helper。
// 自动缓存链路继续直接调用 saveLocalAsset，避免把 external_directory 准入策略扩散到非显式动作。
export async function saveExplicitLocalUserAsset(
  input: SaveExplicitLocalUserAssetInput,
): Promise<SaveExplicitLocalUserAssetResult> {
  const preferredStorageDriver = await resolvePreferredLocalAssetStorageDriver()
  const localAssetRecord = await saveLocalAsset({
    ...input,
    preferredStorageDriver,
  })

  return {
    localAssetRecord,
    preferredStorageDriver,
    didFallbackToBrowserStorage: didLocalAssetExternalDirectoryFallback(
      preferredStorageDriver,
      localAssetRecord.storageDriver,
    ),
  }
}
