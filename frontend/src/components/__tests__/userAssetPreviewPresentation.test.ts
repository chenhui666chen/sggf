import { describe, expect, it } from 'vitest'

import type { UserAssetRecord } from '@/services/api'

import { buildUserAssetPreviewPresentation } from '../user-assets/userAssetPreviewPresentation'

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

describe('userAssetPreviewPresentation', () => {
  it('returns placeholder when preview url is missing', () => {
    expect(
      buildUserAssetPreviewPresentation(createUserAssetRecord(), {
        previewUrl: '',
      }),
    ).toEqual({
      kind: 'placeholder',
      message: '暂无预览',
    })

    expect(
      buildUserAssetPreviewPresentation(createUserAssetRecord(), {
        previewUrl: '',
        isProtectedAssetPending: true,
      }),
    ).toEqual({
      kind: 'placeholder',
      message: '受保护资源加载中...',
    })
  })

  it('returns video and audio presentations by asset kind', () => {
    expect(
      buildUserAssetPreviewPresentation(
        createUserAssetRecord({
          asset_kind: 'video',
        }),
        {
          previewUrl: 'blob:video-preview',
        },
      ),
    ).toEqual({
      kind: 'video',
      src: 'blob:video-preview',
    })

    expect(
      buildUserAssetPreviewPresentation(
        createUserAssetRecord({
          asset_kind: 'audio',
        }),
        {
          previewUrl: 'blob:audio-preview',
        },
      ),
    ).toEqual({
      kind: 'audio',
      src: 'blob:audio-preview',
    })
  })

  it('returns image presentation with normalized alt text', () => {
    expect(
      buildUserAssetPreviewPresentation(
        createUserAssetRecord({
          asset_kind: 'image',
          title: ' 海报终稿 ',
        }),
        {
          previewUrl: 'blob:image-preview',
        },
      ),
    ).toEqual({
      kind: 'image',
      src: 'blob:image-preview',
      alt: '海报终稿',
    })

    expect(
      buildUserAssetPreviewPresentation(
        createUserAssetRecord({
          asset_kind: 'image',
          title: '   ',
        }),
        {
          previewUrl: 'blob:image-preview',
        },
      ),
    ).toEqual({
      kind: 'image',
      src: 'blob:image-preview',
      alt: '用户资产预览',
    })
  })
})
