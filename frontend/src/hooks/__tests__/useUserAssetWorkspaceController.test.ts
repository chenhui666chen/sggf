import { describe, expect, it, vi } from 'vitest'

import type { UserAssetListResponse, UserAssetRecord } from '@/services/api'

import {
  buildUserAssetListRequestParams,
  loadAllUserAssetsForWorkspaceRequestParams,
  probeUserAssetExternalDirectoryAssetHealthSummary,
  resolveExternalDirectoryMissingLocalCopyAssets,
  resolveUserAssetWorkspaceAssetListLoadingState,
} from '../useUserAssetWorkspaceController'

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

function createUserAssetListResponse(overrides: Partial<UserAssetListResponse> = {}): UserAssetListResponse {
  return {
    total: 0,
    page: 1,
    page_size: 200,
    total_pages: 0,
    items: [],
    summary: {
      total_assets: 0,
      active_asset_count: 0,
      archived_asset_count: 0,
      favorite_asset_count: 0,
      reusable_asset_count: 0,
      deliverable_asset_count: 0,
    },
    filter_options: {
      asset_kinds: [],
      source_modules: [],
      tags: [],
    },
    ...overrides,
  }
}

describe('useUserAssetWorkspaceController helpers', () => {
  it('keeps the asset list idle while the workspace is disabled', () => {
    expect(resolveUserAssetWorkspaceAssetListLoadingState({
      enabled: false,
      assetListLoading: true,
      hasLoadedUserAssetsOnce: false,
    })).toBe(false)
  })

  it('shows a loading state before the first asset list request completes', () => {
    expect(resolveUserAssetWorkspaceAssetListLoadingState({
      enabled: true,
      assetListLoading: false,
      hasLoadedUserAssetsOnce: false,
    })).toBe(true)
  })

  it('falls back to the live request state after the first load finishes', () => {
    expect(resolveUserAssetWorkspaceAssetListLoadingState({
      enabled: true,
      assetListLoading: false,
      hasLoadedUserAssetsOnce: true,
    })).toBe(false)
    expect(resolveUserAssetWorkspaceAssetListLoadingState({
      enabled: true,
      assetListLoading: true,
      hasLoadedUserAssetsOnce: true,
    })).toBe(true)
  })

  it('maps workspace filters to paginated user asset request params', () => {
    expect(buildUserAssetListRequestParams({
      filters: {
        viewFilter: 'favorites',
        kindFilter: 'image',
        archiveFilter: 'archived',
        sourceFilter: 'dreamweaver_run',
        tagFilter: '成片',
      },
      page: 3,
      pageSize: 24,
    })).toEqual({
      asset_kind: 'image',
      source_module: 'dreamweaver_run',
      tag: '成片',
      favorites_only: true,
      archive_filter: 'archived',
      page: 3,
      page_size: 24,
    })

    expect(buildUserAssetListRequestParams({
      filters: {
        viewFilter: 'deliverable',
        kindFilter: 'all',
        archiveFilter: 'active',
        sourceFilter: 'all',
        tagFilter: 'all',
      },
      page: 0,
      pageSize: 0,
    })).toEqual({
      asset_class: 'deliverable',
      archive_filter: 'active',
      page: 1,
      page_size: 24,
    })
  })

  it('resolves current-page assets that can directly rebuild missing local copies', () => {
    const assets = [
      createUserAssetRecord({ id: 1, asset_uuid: 'asset-1' }),
      createUserAssetRecord({ id: 2, asset_uuid: 'asset-2' }),
      createUserAssetRecord({ id: 3, asset_uuid: 'asset-3' }),
    ]

    expect(resolveExternalDirectoryMissingLocalCopyAssets(assets, {
      trackedAssetCount: 3,
      inaccessibleAssetCount: 1,
      missingLocalCopyCount: 1,
      inaccessibleAssets: [
        {
          assetId: 1,
          assetUuid: 'asset-1',
          title: '目录不可访问资产',
          sourceModule: 'asset_studio',
          localStorageDriver: 'external_directory',
          localStoragePath: 'image/asset-1.png',
          externalRelativePath: 'image/asset-1.png',
          sourceUri: null,
          previewUri: null,
          downloadUri: null,
        },
      ],
      missingLocalCopyAssets: [
        {
          assetId: 2,
          assetUuid: 'asset-2',
          title: '缺失副本资产',
          sourceModule: 'audiobook',
          localStorageDriver: 'external_directory',
          localStoragePath: 'audio/asset-2.mp3',
          externalRelativePath: 'audio/asset-2.mp3',
          sourceUri: null,
          previewUri: null,
          downloadUri: null,
        },
      ],
    }).map((asset) => asset.id)).toEqual([2])

    expect(resolveExternalDirectoryMissingLocalCopyAssets(assets, null)).toEqual([])
  })

  it('loads all filtered user assets across paginated pages', async () => {
    const listUserAssets = vi.fn()
      .mockResolvedValueOnce({
        data: createUserAssetListResponse({
          total: 3,
          page: 1,
          page_size: 200,
          total_pages: 2,
          items: [
            createUserAssetRecord({ id: 1, asset_uuid: 'asset-1' }),
            createUserAssetRecord({ id: 2, asset_uuid: 'asset-2' }),
          ],
        }),
      })
      .mockResolvedValueOnce({
        data: createUserAssetListResponse({
          total: 3,
          page: 2,
          page_size: 200,
          total_pages: 2,
          items: [
            createUserAssetRecord({ id: 3, asset_uuid: 'asset-3' }),
          ],
        }),
      })

    await expect(loadAllUserAssetsForWorkspaceRequestParams({
      requestParams: buildUserAssetListRequestParams({
        filters: {
          viewFilter: 'all',
          kindFilter: 'all',
          archiveFilter: 'active',
          sourceFilter: 'asset_studio',
          tagFilter: 'all',
        },
        page: 1,
        pageSize: 24,
      }),
      listUserAssets,
    })).resolves.toEqual([
      expect.objectContaining({ id: 1 }),
      expect.objectContaining({ id: 2 }),
      expect.objectContaining({ id: 3 }),
    ])

    expect(listUserAssets).toHaveBeenCalledTimes(2)
    expect(listUserAssets).toHaveBeenNthCalledWith(1, expect.objectContaining({
      page: 1,
      limit: 200,
      source_module: 'asset_studio',
    }))
    expect(listUserAssets).toHaveBeenNthCalledWith(2, expect.objectContaining({
      page: 2,
      limit: 200,
      source_module: 'asset_studio',
    }))
  })

  it('probes external-directory asset health and returns missing local copies', async () => {
    const getLocalAssetBlobByUuid = vi.fn(async (assetUuid: string) => {
      if (assetUuid === 'asset-1') {
        return new Blob(['ok'])
      }
      return null
    })

    await expect(probeUserAssetExternalDirectoryAssetHealthSummary(
      [
        createUserAssetRecord({
          id: 1,
          asset_uuid: 'asset-1',
          metadata_json: {
            local_storage_driver: 'external_directory',
            local_storage_path: 'image/asset-1.png',
            external_relative_path: 'image/asset-1.png',
          },
        }),
        createUserAssetRecord({
          id: 2,
          asset_uuid: 'asset-2',
          metadata_json: {
            local_storage_driver: 'external_directory',
            local_storage_path: 'image/asset-2.png',
            external_relative_path: 'image/asset-2.png',
          },
        }),
        createUserAssetRecord({
          id: 3,
          asset_uuid: 'asset-3',
          metadata_json: {
            local_storage_driver: 'opfs',
          },
        }),
      ],
      {
        supported: true,
        configured: true,
        directoryName: 'Novel Assets',
        permission: 'granted',
      },
      { getLocalAssetBlobByUuid },
    )).resolves.toMatchObject({
      trackedAssetCount: 2,
      inaccessibleAssetCount: 0,
      missingLocalCopyCount: 1,
      missingLocalCopyAssets: [
        expect.objectContaining({
          assetId: 2,
          assetUuid: 'asset-2',
          externalRelativePath: 'image/asset-2.png',
        }),
      ],
    })
  })
})
