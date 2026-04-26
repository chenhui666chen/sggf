import { describe, expect, it, vi } from 'vitest'

import type { UserAssetRecord } from '@/services/api'

import type { LocalAssetVaultRecord } from '../localAssetVault'
import {
  isUserAssetLocalRestoreEligible,
  restoreUserAssetLocalCopy,
} from '../userAssetLocalRecovery'

function createUserAssetRecord(overrides: Partial<UserAssetRecord> = {}): UserAssetRecord {
  return {
    id: 1,
    user_id: 1,
    source_module: 'asset_studio',
    asset_kind: 'image',
    asset_class: 'reusable',
    asset_uuid: 'asset-1',
    storage_mode: 'local_mirror',
    title: '测试资产',
    description: '用于恢复测试',
    source_uri: 'https://example.com/source.png',
    preview_uri: 'https://example.com/preview.png',
    download_uri: 'https://example.com/download.png',
    mime_type: 'image/png',
    file_size: 128,
    tags: [],
    metadata_json: {},
    is_favorite: false,
    created_at: '2026-04-23T00:00:00Z',
    updated_at: '2026-04-23T00:00:00Z',
    ...overrides,
  }
}

function createLocalAssetVaultRecord(overrides: Partial<LocalAssetVaultRecord> = {}): LocalAssetVaultRecord {
  return {
    assetUuid: 'asset-1',
    mediaKind: 'image',
    blob: new Blob(['local-copy'], { type: 'image/png' }),
    mimeType: 'image/png',
    fileSize: 128,
    sourceModule: 'asset_studio',
    title: '测试资产',
    sourceUri: 'https://example.com/source.png',
    previewUri: 'https://example.com/preview.png',
    downloadUri: 'https://example.com/download.png',
    metadata: {},
    createdAt: '2026-04-23T00:00:00Z',
    updatedAt: '2026-04-23T00:00:00Z',
    storageDriver: 'opfs',
    storagePath: 'local_asset_vault/image/asset-1',
    externalRelativePath: null,
    persistLevel: 'persistent_requested',
    ...overrides,
  }
}

describe('userAssetLocalRecovery', () => {
  it('identifies whether an asset is eligible for local restore', () => {
    expect(isUserAssetLocalRestoreEligible(createUserAssetRecord())).toBe(true)
    expect(
      isUserAssetLocalRestoreEligible(createUserAssetRecord({ storage_mode: 'durable_cloud' })),
    ).toBe(false)
    expect(
      isUserAssetLocalRestoreEligible(createUserAssetRecord({ asset_uuid: '   ' })),
    ).toBe(false)
  })

  it('returns already_present when the current browser already has a local copy', async () => {
    const fetchSourceBlob = vi.fn()
    const saveAsset = vi.fn()

    const result = await restoreUserAssetLocalCopy(createUserAssetRecord(), {
      getExistingLocalBlob: vi.fn().mockResolvedValue(new Blob(['existing'], { type: 'image/png' })),
      fetchSourceBlob,
      saveAsset,
    })

    expect(result).toEqual({ status: 'already_present' })
    expect(fetchSourceBlob).not.toHaveBeenCalled()
    expect(saveAsset).not.toHaveBeenCalled()
  })

  it('blocks restore when the registered external directory is unavailable', async () => {
    const fetchSourceBlob = vi.fn()
    const saveAsset = vi.fn()

    const result = await restoreUserAssetLocalCopy(
      createUserAssetRecord({
        metadata_json: {
          local_storage_driver: 'external_directory',
        },
      }),
      {
        getExistingLocalBlob: vi.fn().mockResolvedValue(null),
        getExternalDirectoryStatus: vi.fn().mockResolvedValue({
          supported: true,
          configured: true,
          directoryName: 'Novel Assets',
          permission: 'denied',
        }),
        fetchSourceBlob,
        saveAsset,
      },
    )

    expect(result).toMatchObject({
      status: 'blocked',
      reason: 'external_directory_unavailable',
    })
    expect(fetchSourceBlob).not.toHaveBeenCalled()
    expect(saveAsset).not.toHaveBeenCalled()
  })

  it('rolls back the written copy when the actual storage driver does not match the registered driver', async () => {
    const sourceBlob = new Blob(['remote-copy'], { type: 'audio/mpeg' })
    const fetchSourceBlob = vi.fn().mockResolvedValue(sourceBlob)
    const saveAsset = vi.fn().mockResolvedValue(createLocalAssetVaultRecord({
      mediaKind: 'audio',
      blob: sourceBlob,
      mimeType: 'audio/mpeg',
      fileSize: sourceBlob.size,
      storageDriver: 'opfs',
      storagePath: 'local_asset_vault/audio/asset-1',
      persistLevel: 'persistent_requested',
    }))
    const deleteAsset = vi.fn().mockResolvedValue(true)

    const result = await restoreUserAssetLocalCopy(
      createUserAssetRecord({
        asset_kind: 'audio',
        mime_type: 'audio/mpeg',
        file_size: sourceBlob.size,
        metadata_json: {
          local_storage_driver: 'external_directory',
        },
      }),
      {
        getExistingLocalBlob: vi.fn().mockResolvedValue(null),
        getExternalDirectoryStatus: vi.fn().mockResolvedValue({
          supported: true,
          configured: true,
          directoryName: 'Novel Assets',
          permission: 'granted',
        }),
        fetchSourceBlob,
        saveAsset,
        deleteAsset,
      },
    )

    expect(result).toMatchObject({
      status: 'blocked',
      reason: 'storage_driver_mismatch',
    })
    expect(saveAsset).toHaveBeenCalledWith(expect.objectContaining({
      assetUuid: 'asset-1',
      mediaKind: 'audio',
      blob: sourceBlob,
      preferredStorageDriver: 'external_directory',
    }))
    expect(deleteAsset).toHaveBeenCalledWith('asset-1')
  })

  it('restores the local copy with the registered storage driver when the source blob can be loaded', async () => {
    const sourceBlob = new Blob(['remote-copy'], { type: 'image/png' })
    const fetchSourceBlob = vi.fn().mockResolvedValue(sourceBlob)
    const saveAsset = vi.fn().mockResolvedValue(createLocalAssetVaultRecord({
      blob: sourceBlob,
      storageDriver: 'external_directory',
      storagePath: 'image/asset-1.png',
      externalRelativePath: 'image/asset-1.png',
      persistLevel: 'user_directory',
      metadata: {
        local_storage_driver: 'external_directory',
      },
    }))

    const result = await restoreUserAssetLocalCopy(
      createUserAssetRecord({
        metadata_json: {
          local_storage_driver: 'external_directory',
        },
      }),
      {
        getExistingLocalBlob: vi.fn().mockResolvedValue(null),
        getExternalDirectoryStatus: vi.fn().mockResolvedValue({
          supported: true,
          configured: true,
          directoryName: 'Novel Assets',
          permission: 'granted',
        }),
        fetchSourceBlob,
        saveAsset,
      },
    )

    expect(result).toMatchObject({
      status: 'restored',
      storageDriver: 'external_directory',
    })
    expect(fetchSourceBlob).toHaveBeenCalledTimes(1)
    expect(saveAsset).toHaveBeenCalledWith(expect.objectContaining({
      assetUuid: 'asset-1',
      mediaKind: 'image',
      blob: sourceBlob,
      mimeType: 'image/png',
      fileSize: 128,
      sourceModule: 'asset_studio',
      title: '测试资产',
      preferredStorageDriver: 'external_directory',
      metadata: expect.objectContaining({
        local_storage_driver: 'external_directory',
      }),
    }))
  })
})
