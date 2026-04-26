import { describe, expect, it } from 'vitest'

import type { UserAssetRecord } from '@/services/api'

import {
  collectUserAssetLocalPreviewTargets,
  collectUserAssetProtectedPreviewTargets,
} from '../useUserAssetPreviewObjectUrls'

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

describe('useUserAssetPreviewObjectUrls helpers', () => {
  it('collects local preview targets from assets with non-empty asset_uuid', () => {
    expect(
      collectUserAssetLocalPreviewTargets([
        createUserAssetRecord({ id: 1, asset_uuid: ' asset-1 ' }),
        createUserAssetRecord({ id: 2, asset_uuid: '' }),
      ]),
    ).toEqual([
      {
        assetId: 1,
        assetUuid: 'asset-1',
      },
    ])
  })

  it('collects protected preview targets and skips assets already backed by local object urls', () => {
    const assets = [
      createUserAssetRecord({
        id: 1,
        source_module: 'dreamweaver_library',
        source_payload_json: { asset_id: 12 },
      }),
      createUserAssetRecord({
        id: 2,
        source_module: 'dreamweaver_run',
        metadata_json: { run_id: 'run-22' },
      }),
      createUserAssetRecord({
        id: 3,
        source_module: 'audiobook',
        source_payload_json: { audiobook_project_id: 21, chapter_id: 7 },
      }),
      createUserAssetRecord({
        id: 4,
        source_module: 'asset_studio',
      }),
    ]

    expect(
      collectUserAssetProtectedPreviewTargets(assets, {
        2: 'blob:local-run-preview',
      }),
    ).toEqual([
      {
        assetId: 1,
        kind: 'dreamweaver_library',
        libraryAssetId: 12,
      },
      {
        assetId: 3,
        kind: 'audiobook',
        audiobookProjectId: 21,
        chapterId: 7,
      },
    ])
  })
})
