import { describe, expect, it } from 'vitest'

import type { UserAssetRecord } from '@/services/api'

import { buildUserAssetCardPreviewBridge } from '../user-assets/userAssetPreviewBridge'

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

describe('userAssetPreviewBridge', () => {
  it('reads local and protected object urls by asset id', () => {
    const bridge = buildUserAssetCardPreviewBridge(createUserAssetRecord({ id: 9 }), {
      localObjectUrls: { 9: ' blob:local-preview ' },
      protectedObjectUrls: { 9: ' blob:protected-preview ' },
    })

    expect(bridge).toEqual({
      localObjectUrl: 'blob:local-preview',
      protectedObjectUrl: 'blob:protected-preview',
    })
  })

  it('falls back to null when object urls are missing or empty', () => {
    const bridge = buildUserAssetCardPreviewBridge(createUserAssetRecord({ id: 12 }), {
      localObjectUrls: { 12: '   ' },
    })

    expect(bridge).toEqual({
      localObjectUrl: null,
      protectedObjectUrl: null,
    })
  })
})
