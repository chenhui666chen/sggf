import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { LocalAssetVaultRecord } from '../localAssetVault'

const {
  didLocalAssetExternalDirectoryFallbackMock,
  resolvePreferredLocalAssetStorageDriverMock,
  saveLocalAssetMock,
} = vi.hoisted(() => ({
  didLocalAssetExternalDirectoryFallbackMock: vi.fn(),
  resolvePreferredLocalAssetStorageDriverMock: vi.fn(),
  saveLocalAssetMock: vi.fn(),
}))

vi.mock('../localAssetExternalDirectory', () => ({
  didLocalAssetExternalDirectoryFallback: didLocalAssetExternalDirectoryFallbackMock,
  resolvePreferredLocalAssetStorageDriver: resolvePreferredLocalAssetStorageDriverMock,
}))

vi.mock('../localAssetVault', () => ({
  saveLocalAsset: saveLocalAssetMock,
}))

import { saveExplicitLocalUserAsset } from '../userAssetExplicitLocalCollection'

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
    createdAt: '2026-04-24T00:00:00Z',
    updatedAt: '2026-04-24T00:00:00Z',
    storageDriver: 'opfs',
    storagePath: 'local_asset_vault/image/asset-1',
    externalRelativePath: null,
    persistLevel: 'persistent_requested',
    ...overrides,
  }
}

describe('userAssetExplicitLocalCollection', () => {
  beforeEach(() => {
    didLocalAssetExternalDirectoryFallbackMock.mockReset()
    resolvePreferredLocalAssetStorageDriverMock.mockReset()
    saveLocalAssetMock.mockReset()
  })

  it('applies the preferred storage driver audit before saving an explicit local asset', async () => {
    const localAssetRecord = createLocalAssetVaultRecord({
      storageDriver: 'external_directory',
      storagePath: 'image/asset-1.png',
      externalRelativePath: 'image/asset-1.png',
      persistLevel: 'user_directory',
      metadata: {
        local_storage_driver: 'external_directory',
      },
    })
    resolvePreferredLocalAssetStorageDriverMock.mockResolvedValue('external_directory')
    saveLocalAssetMock.mockResolvedValue(localAssetRecord)
    didLocalAssetExternalDirectoryFallbackMock.mockReturnValue(false)

    const result = await saveExplicitLocalUserAsset({
      assetUuid: 'asset-1',
      mediaKind: 'image',
      blob: new Blob(['asset'], { type: 'image/png' }),
      sourceModule: 'asset_studio',
      title: '测试资产',
    })

    expect(resolvePreferredLocalAssetStorageDriverMock).toHaveBeenCalledTimes(1)
    expect(saveLocalAssetMock).toHaveBeenCalledWith(expect.objectContaining({
      assetUuid: 'asset-1',
      mediaKind: 'image',
      preferredStorageDriver: 'external_directory',
    }))
    expect(didLocalAssetExternalDirectoryFallbackMock).toHaveBeenCalledWith(
      'external_directory',
      'external_directory',
    )
    expect(result).toEqual({
      localAssetRecord,
      preferredStorageDriver: 'external_directory',
      didFallbackToBrowserStorage: false,
    })
  })

  it('returns the browser fallback flag when the preferred external directory was not used', async () => {
    const localAssetRecord = createLocalAssetVaultRecord({
      storageDriver: 'opfs',
      persistLevel: 'persistent_requested',
    })
    resolvePreferredLocalAssetStorageDriverMock.mockResolvedValue('external_directory')
    saveLocalAssetMock.mockResolvedValue(localAssetRecord)
    didLocalAssetExternalDirectoryFallbackMock.mockReturnValue(true)

    const result = await saveExplicitLocalUserAsset({
      assetUuid: 'asset-2',
      mediaKind: 'audio',
      blob: new Blob(['asset'], { type: 'audio/mpeg' }),
      sourceModule: 'audiobook',
      title: '章节音频',
    })

    expect(didLocalAssetExternalDirectoryFallbackMock).toHaveBeenCalledWith(
      'external_directory',
      'opfs',
    )
    expect(result.didFallbackToBrowserStorage).toBe(true)
  })
})
