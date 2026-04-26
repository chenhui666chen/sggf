import { describe, expect, it, vi } from 'vitest'

import type { UserAssetRecord } from '@/services/api'

import {
  executeUserAssetLocalClearAction,
  executeUserAssetLocalClearBatch,
  executeUserAssetLocalRestoreAction,
  executeUserAssetLocalRestoreBatch,
  isClearLocalCopyEligibleAsset,
} from '../userAssetWorkspaceLocalActions'

function createUserAssetRecord(overrides: Partial<UserAssetRecord> = {}): UserAssetRecord {
  return {
    id: 1,
    user_id: 1,
    source_module: 'asset_studio',
    asset_kind: 'image',
    asset_class: 'reusable',
    asset_uuid: 'asset-1',
    storage_mode: 'local_mirror',
    title: 'asset',
    tags: [],
    is_favorite: false,
    created_at: '2026-04-23T00:00:00Z',
    updated_at: '2026-04-23T00:00:00Z',
    ...overrides,
  }
}

describe('userAssetWorkspaceLocalActions', () => {
  it('identifies whether an asset can clear its local copy', () => {
    expect(isClearLocalCopyEligibleAsset(createUserAssetRecord())).toBe(true)
    expect(
      isClearLocalCopyEligibleAsset(createUserAssetRecord({ storage_mode: 'durable_cloud' })),
    ).toBe(false)
    expect(
      isClearLocalCopyEligibleAsset(createUserAssetRecord({ asset_uuid: '   ' })),
    ).toBe(false)
  })

  it('runs single restore action only for eligible assets', async () => {
    const restoreLocalCopy = vi.fn().mockResolvedValue({
      status: 'already_present' as const,
    })

    await expect(
      executeUserAssetLocalRestoreAction(
        createUserAssetRecord({ id: 9 }),
        { restoreLocalCopy },
      ),
    ).resolves.toEqual({
      status: 'already_present',
    })
    await expect(
      executeUserAssetLocalRestoreAction(
        createUserAssetRecord({ id: 10, storage_mode: 'durable_cloud' }),
        { restoreLocalCopy },
      ),
    ).resolves.toEqual({
      status: 'skipped',
    })
    expect(restoreLocalCopy).toHaveBeenCalledTimes(1)
    expect(restoreLocalCopy).toHaveBeenCalledWith(expect.objectContaining({ id: 9 }))
  })

  it('runs single clear action only for eligible assets and trims asset uuid', async () => {
    const deleteLocalCopy = vi.fn().mockResolvedValue(true)

    await expect(
      executeUserAssetLocalClearAction(
        createUserAssetRecord({ id: 11, asset_uuid: ' asset-11 ' }),
        { deleteLocalCopy },
      ),
    ).resolves.toEqual({
      status: 'cleared',
      cleared: true,
    })
    await expect(
      executeUserAssetLocalClearAction(
        createUserAssetRecord({ id: 12, asset_uuid: '   ' }),
        { deleteLocalCopy },
      ),
    ).resolves.toEqual({
      status: 'skipped',
    })
    expect(deleteLocalCopy).toHaveBeenCalledTimes(1)
    expect(deleteLocalCopy).toHaveBeenCalledWith('asset-11')
  })

  it('summarizes batch restore results and keeps blocked or failed assets selected', async () => {
    const restoreLocalCopy = vi.fn(async (asset: UserAssetRecord) => {
      if (asset.id === 1) {
        return {
          status: 'restored' as const,
          storageDriver: 'opfs' as const,
          localAssetRecord: {
            assetUuid: 'asset-1',
            mediaKind: 'image',
            blob: new Blob(['restored']),
            createdAt: '2026-04-23T00:00:00Z',
            updatedAt: '2026-04-23T00:00:00Z',
            storageDriver: 'opfs' as const,
            persistLevel: 'persistent_requested' as const,
          },
        }
      }

      if (asset.id === 2) {
        return {
          status: 'already_present' as const,
        }
      }

      if (asset.id === 3) {
        return {
          status: 'blocked' as const,
          reason: 'external_directory_unavailable' as const,
          message: '用户目录当前不可用',
        }
      }

      throw new Error('boom')
    })

    const summary = await executeUserAssetLocalRestoreBatch([
      createUserAssetRecord({ id: 1, asset_uuid: 'asset-1' }),
      createUserAssetRecord({ id: 2, asset_uuid: 'asset-2' }),
      createUserAssetRecord({ id: 3, asset_uuid: 'asset-3' }),
      createUserAssetRecord({ id: 4, asset_uuid: 'asset-4' }),
      createUserAssetRecord({ id: 5, storage_mode: 'durable_cloud', asset_uuid: 'asset-5' }),
    ], {
      restoreLocalCopy,
    })

    expect(summary).toEqual({
      targetAssetCount: 4,
      handledIds: [1, 2],
      restoredCount: 1,
      existingCount: 1,
      blockedCount: 1,
      failedCount: 1,
    })
    expect(restoreLocalCopy).toHaveBeenCalledTimes(4)
  })

  it('summarizes batch clear results and skips ineligible assets', async () => {
    const deleteLocalCopy = vi.fn(async (assetUuid: string) => {
      if (assetUuid === 'asset-1') {
        return true
      }
      if (assetUuid === 'asset-2') {
        return false
      }
      throw new Error('delete failed')
    })

    const summary = await executeUserAssetLocalClearBatch([
      createUserAssetRecord({ id: 1, asset_uuid: ' asset-1 ' }),
      createUserAssetRecord({ id: 2, asset_uuid: 'asset-2' }),
      createUserAssetRecord({ id: 3, asset_uuid: 'asset-3' }),
      createUserAssetRecord({ id: 4, storage_mode: 'durable_cloud', asset_uuid: 'asset-4' }),
    ], {
      deleteLocalCopy,
    })

    expect(summary).toEqual({
      targetAssetCount: 3,
      handledIds: [1, 2],
      clearedCount: 1,
      missingCount: 1,
      failedCount: 1,
    })
    expect(deleteLocalCopy).toHaveBeenCalledTimes(3)
    expect(deleteLocalCopy).toHaveBeenNthCalledWith(1, 'asset-1')
  })
})
