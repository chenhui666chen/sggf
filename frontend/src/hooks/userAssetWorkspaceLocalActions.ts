import type { UserAssetRecord } from '@/services/api'
import {
  isUserAssetLocalRestoreEligible,
  restoreUserAssetLocalCopy,
  type RestoreUserAssetLocalCopyResult,
} from '@/utils/userAssetLocalRecovery'
import { deleteLocalAsset } from '@/utils/localAssetVault'

export type UserAssetLocalRestoreBatchSummary = {
  targetAssetCount: number
  handledIds: number[]
  restoredCount: number
  existingCount: number
  blockedCount: number
  failedCount: number
}

export type UserAssetLocalClearBatchSummary = {
  targetAssetCount: number
  handledIds: number[]
  clearedCount: number
  missingCount: number
  failedCount: number
}

export type UserAssetLocalRestoreActionResult =
  | {
      status: 'skipped'
    }
  | RestoreUserAssetLocalCopyResult

export type UserAssetLocalClearActionResult =
  | {
      status: 'skipped'
    }
  | {
      status: 'cleared'
      cleared: boolean
    }

type RestoreUserAssetLocalCopyDependency = (
  asset: UserAssetRecord,
) => Promise<RestoreUserAssetLocalCopyResult>

type DeleteLocalAssetDependency = (assetUuid: string) => Promise<boolean>

function readTrimmedString(value: string | null | undefined): string {
  return String(value || '').trim()
}

export function isClearLocalCopyEligibleAsset(
  asset: Pick<UserAssetRecord, 'storage_mode' | 'asset_uuid'>,
): boolean {
  return asset.storage_mode === 'local_mirror' && Boolean(readTrimmedString(asset.asset_uuid))
}

export async function executeUserAssetLocalRestoreAction(
  asset: UserAssetRecord,
  dependencies: {
    restoreLocalCopy?: RestoreUserAssetLocalCopyDependency
  } = {},
): Promise<UserAssetLocalRestoreActionResult> {
  if (!isUserAssetLocalRestoreEligible(asset)) {
    return { status: 'skipped' }
  }

  const restoreLocalCopy = dependencies.restoreLocalCopy ?? restoreUserAssetLocalCopy
  return restoreLocalCopy(asset)
}

export async function executeUserAssetLocalClearAction(
  asset: Pick<UserAssetRecord, 'storage_mode' | 'asset_uuid'>,
  dependencies: {
    deleteLocalCopy?: DeleteLocalAssetDependency
  } = {},
): Promise<UserAssetLocalClearActionResult> {
  if (!isClearLocalCopyEligibleAsset(asset)) {
    return { status: 'skipped' }
  }

  const deleteLocalCopy = dependencies.deleteLocalCopy ?? deleteLocalAsset
  return {
    status: 'cleared',
    cleared: await deleteLocalCopy(readTrimmedString(asset.asset_uuid)),
  }
}

export async function executeUserAssetLocalRestoreBatch(
  assets: UserAssetRecord[],
  dependencies: {
    restoreLocalCopy?: RestoreUserAssetLocalCopyDependency
  } = {},
): Promise<UserAssetLocalRestoreBatchSummary> {
  const targetAssets = assets.filter(isUserAssetLocalRestoreEligible)

  if (!targetAssets.length) {
    return {
      targetAssetCount: 0,
      handledIds: [],
      restoredCount: 0,
      existingCount: 0,
      blockedCount: 0,
      failedCount: 0,
    }
  }

  const results = await Promise.allSettled(
    targetAssets.map((asset) => executeUserAssetLocalRestoreAction(asset, dependencies)),
  )
  const summary: UserAssetLocalRestoreBatchSummary = {
    targetAssetCount: targetAssets.length,
    handledIds: [],
    restoredCount: 0,
    existingCount: 0,
    blockedCount: 0,
    failedCount: 0,
  }

  results.forEach((result, index) => {
    const asset = targetAssets[index]
    if (result.status === 'rejected') {
      summary.failedCount += 1
      return
    }

    if (result.value.status === 'skipped') {
      return
    }

    if (result.value.status === 'restored') {
      summary.restoredCount += 1
      summary.handledIds.push(asset.id)
      return
    }

    if (result.value.status === 'already_present') {
      summary.existingCount += 1
      summary.handledIds.push(asset.id)
      return
    }

    summary.blockedCount += 1
  })

  return summary
}

export async function executeUserAssetLocalClearBatch(
  assets: UserAssetRecord[],
  dependencies: {
    deleteLocalCopy?: DeleteLocalAssetDependency
  } = {},
): Promise<UserAssetLocalClearBatchSummary> {
  const targetAssets = assets.filter(isClearLocalCopyEligibleAsset)

  if (!targetAssets.length) {
    return {
      targetAssetCount: 0,
      handledIds: [],
      clearedCount: 0,
      missingCount: 0,
      failedCount: 0,
    }
  }

  const results = await Promise.allSettled(
    targetAssets.map((asset) => executeUserAssetLocalClearAction(asset, dependencies)),
  )
  const summary: UserAssetLocalClearBatchSummary = {
    targetAssetCount: targetAssets.length,
    handledIds: [],
    clearedCount: 0,
    missingCount: 0,
    failedCount: 0,
  }

  results.forEach((result, index) => {
    const asset = targetAssets[index]
    if (result.status === 'rejected') {
      summary.failedCount += 1
      return
    }

    if (result.value.status === 'skipped') {
      return
    }

    summary.handledIds.push(asset.id)
    if (result.value.cleared) {
      summary.clearedCount += 1
      return
    }

    summary.missingCount += 1
  })

  return summary
}
