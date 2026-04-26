import { describe, expect, it } from 'vitest'

import type { UserAssetRecord } from '@/services/api'

import {
  extractAudiobookChapterAssetRef,
  extractAudiobookChapterTraceInfo,
  extractDreamweaverLibraryAssetId,
  extractDreamweaverLibraryTraceInfo,
  extractDreamweaverMergedRunId,
  extractUserAssetProjectId,
  getUserAssetMetadataPayload,
  getUserAssetSourcePayload,
} from '../userAssetSourcePayloadSelectors'

function createUserAssetRecord(
  overrides: Partial<UserAssetRecord> = {},
): UserAssetRecord {
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

describe('userAssetSourcePayloadSelectors', () => {
  it('returns safe payload and metadata objects', () => {
    const asset = createUserAssetRecord({
      source_payload_json: { project_id: 8 },
      metadata_json: { local_storage_driver: 'opfs' },
    })

    expect(getUserAssetSourcePayload(asset)).toEqual({ project_id: 8 })
    expect(getUserAssetMetadataPayload(asset)).toEqual({ local_storage_driver: 'opfs' })
    expect(getUserAssetSourcePayload(createUserAssetRecord({ source_payload_json: null as never }))).toEqual({})
  })

  it('extracts project id with direct field first, then payload, then metadata', () => {
    expect(
      extractUserAssetProjectId(
        createUserAssetRecord({
          project_id: 7,
          source_payload_json: { project_id: 8 },
          metadata_json: { project_id: 9 },
        }),
      ),
    ).toBe(7)

    expect(
      extractUserAssetProjectId(
        createUserAssetRecord({
          project_id: null,
          source_payload_json: { project_id: 8 },
          metadata_json: { project_id: 9 },
        }),
      ),
    ).toBe(8)

    expect(
      extractUserAssetProjectId(
        createUserAssetRecord({
          project_id: null,
          source_payload_json: {},
          metadata_json: { project_id: 9 },
        }),
      ),
    ).toBe(9)
  })

  it('extracts dreamweaver library asset id, merged run id and trace info with payload/metadata fallback', () => {
    const libraryAsset = createUserAssetRecord({
      source_payload_json: { asset_id: '12' },
      metadata_json: { library_asset_id: '13', entity_type: 'character', view: 'front' },
    })
    const runAsset = createUserAssetRecord({
      source_payload_json: {},
      metadata_json: { run_id: 'run-22' },
    })

    expect(extractDreamweaverLibraryAssetId(libraryAsset)).toBe(12)
    expect(extractDreamweaverLibraryTraceInfo(libraryAsset)).toEqual({
      entityType: 'character',
      view: 'front',
    })
    expect(extractDreamweaverMergedRunId(runAsset)).toBe('run-22')
  })

  it('extracts audiobook chapter refs and trace info from payload/metadata fallback', () => {
    const asset = createUserAssetRecord({
      source_payload_json: {
        audiobook_project_id: '21',
        chapter_id: '7',
      },
      metadata_json: {
        chapter_number: '3',
        chapter_title: '山雨欲来',
      },
    })

    expect(extractAudiobookChapterAssetRef(asset)).toEqual({
      audiobookProjectId: 21,
      chapterId: 7,
    })
    expect(extractAudiobookChapterTraceInfo(asset)).toEqual({
      audiobookProjectId: 21,
      chapterId: 7,
      chapterNumber: 3,
      chapterTitle: '山雨欲来',
    })
  })
})
