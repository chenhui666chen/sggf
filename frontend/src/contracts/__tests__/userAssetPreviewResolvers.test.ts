import { describe, expect, it, vi } from 'vitest'

import type { UserAssetRecord } from '@/services/api'

import {
  fetchProtectedUserAssetBlob,
  getUserAssetRemotePreviewUrl,
  isUserAssetPreviewPending,
  resolveUserAssetPreviewUrl,
} from '../userAssetPreviewResolvers'

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

describe('userAssetPreviewResolvers', () => {
  it('selects remote preview url with preview_uri first, then source_uri, then download_uri', () => {
    expect(
      getUserAssetRemotePreviewUrl(
        createUserAssetRecord({
          preview_uri: '  ',
          source_uri: 'https://example.com/source.png',
          download_uri: 'https://example.com/download.png',
        }),
      ),
    ).toBe('https://example.com/source.png')

    expect(
      getUserAssetRemotePreviewUrl(
        createUserAssetRecord({
          preview_uri: 'https://example.com/preview.png',
          source_uri: 'https://example.com/source.png',
        }),
      ),
    ).toBe('https://example.com/preview.png')
  })

  it('resolves preview url with local first, then protected object url, then non-protected remote url', () => {
    const asset = createUserAssetRecord({
      preview_uri: 'https://example.com/preview.png',
      source_uri: 'https://example.com/source.png',
    })

    expect(
      resolveUserAssetPreviewUrl(asset, {
        localObjectUrl: 'blob:local-preview',
        protectedObjectUrl: 'blob:protected-preview',
      }),
    ).toBe('blob:local-preview')

    expect(
      resolveUserAssetPreviewUrl(asset, {
        protectedObjectUrl: 'blob:protected-preview',
      }),
    ).toBe('blob:protected-preview')

    expect(resolveUserAssetPreviewUrl(asset)).toBe('https://example.com/preview.png')
  })

  it('keeps protected assets pending until local or protected object url becomes available', () => {
    const protectedAsset = createUserAssetRecord({
      source_module: 'dreamweaver_run',
      preview_uri: 'https://example.com/protected-preview.mp4',
      metadata_json: { run_id: 'run-22' },
    })

    expect(resolveUserAssetPreviewUrl(protectedAsset)).toBe('')
    expect(isUserAssetPreviewPending(protectedAsset)).toBe(true)
    expect(
      resolveUserAssetPreviewUrl(protectedAsset, {
        protectedObjectUrl: 'blob:protected-preview',
      }),
    ).toBe('blob:protected-preview')
    expect(
      isUserAssetPreviewPending(protectedAsset, {
        protectedObjectUrl: 'blob:protected-preview',
      }),
    ).toBe(false)
  })

  it('dispatches protected asset blob loading by protected ref kind', async () => {
    const libraryBlob = new Blob(['library'])
    const runBlob = new Blob(['run'])
    const audiobookBlob = new Blob(['audiobook'])
    const loaders = {
      fetchDreamweaverLibraryAssetFile: vi.fn().mockResolvedValue(libraryBlob),
      fetchDreamweaverMergedVideoFile: vi.fn().mockResolvedValue(runBlob),
      fetchAudiobookChapterAudioFile: vi.fn().mockResolvedValue(audiobookBlob),
    }

    await expect(
      fetchProtectedUserAssetBlob(
        {
          kind: 'dreamweaver_library',
          libraryAssetId: 12,
        },
        loaders,
      ),
    ).resolves.toBe(libraryBlob)

    await expect(
      fetchProtectedUserAssetBlob(
        {
          kind: 'dreamweaver_run',
          runId: 'run-22',
        },
        loaders,
      ),
    ).resolves.toBe(runBlob)

    await expect(
      fetchProtectedUserAssetBlob(
        {
          kind: 'audiobook',
          audiobookProjectId: 21,
          chapterId: 7,
        },
        loaders,
      ),
    ).resolves.toBe(audiobookBlob)

    expect(loaders.fetchDreamweaverLibraryAssetFile).toHaveBeenCalledWith(12)
    expect(loaders.fetchDreamweaverMergedVideoFile).toHaveBeenCalledWith('run-22')
    expect(loaders.fetchAudiobookChapterAudioFile).toHaveBeenCalledWith(21, 7)
  })
})
