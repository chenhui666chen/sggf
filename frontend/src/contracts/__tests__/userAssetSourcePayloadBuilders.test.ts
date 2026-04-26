import { describe, expect, it } from 'vitest'

import {
  buildAssetStudioCollectedSourcePayload,
  buildAudiobookChapterAudioSourcePayload,
  buildDreamWeaverLibrarySourcePayload,
  buildDreamWeaverMergedVideoSourcePayload,
  buildUserAssetSourcePayload,
} from '../userAssetSourcePayloadBuilders'

describe('userAssetSourcePayloadBuilders', () => {
  it('merges source payload parts in order', () => {
    const payload = buildUserAssetSourcePayload(
      { module: 'asset_studio', project_id: 1 },
      null,
      { project_id: 2, extra_flag: true },
    )

    expect(payload).toEqual({
      module: 'asset_studio',
      project_id: 2,
      extra_flag: true,
    })
  })

  it('builds asset studio collected source payload with stable keys', () => {
    const payload = buildAssetStudioCollectedSourcePayload({
      kind: 'image',
      mode: 'generate',
      modelId: 'model-a',
      assets: [],
      primaryAsset: null,
      metadata: { prompt: 'cover' },
    })

    expect(payload).toEqual({
      kind: 'image',
      mode: 'generate',
      model_id: 'model-a',
      assets: [],
      primary_asset: null,
      metadata: { prompt: 'cover' },
    })
  })

  it('builds audiobook chapter audio source payload by extending asset metadata', () => {
    const payload = buildAudiobookChapterAudioSourcePayload({
      chapter_id: 7,
      chapter_title: '第七章',
      local_storage_driver: 'opfs',
      local_storage_path: 'local_asset_vault/audio/asset-1',
      local_persist_level: 'persistent_requested',
      external_relative_path: 'chapter-7/audio.mp3',
    })

    expect(payload).toEqual({
      chapter_id: 7,
      chapter_title: '第七章',
      type: 'chapter_audio',
    })
  })

  it('builds dreamweaver library and merged video payloads with explicit field names', () => {
    const libraryPayload = buildDreamWeaverLibrarySourcePayload({
      projectId: 8,
      assetId: 'asset-1',
      role: 'reference',
      uri: '/library/asset-1',
      entityType: 'character',
      entityId: 'char-1',
      view: 'front',
      approved: true,
    })
    const mergedVideoPayload = buildDreamWeaverMergedVideoSourcePayload({
      runId: 'run-9',
      projectId: 8,
      path: '/tmp/merged.mp4',
    })

    expect(libraryPayload).toEqual({
      project_id: 8,
      asset_id: 'asset-1',
      role: 'reference',
      uri: '/library/asset-1',
      entity_type: 'character',
      entity_id: 'char-1',
      view: 'front',
      approved: true,
    })
    expect(mergedVideoPayload).toEqual({
      run_id: 'run-9',
      project_id: 8,
      type: 'merged_video',
      path: '/tmp/merged.mp4',
    })
  })
})
