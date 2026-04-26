import { describe, expect, it } from 'vitest'

import {
  buildAssetStudioCollectedAssetMetadataContract,
  buildAudiobookChapterAudioAssetMetadataContract,
  buildDreamWeaverLibraryAssetMetadataContract,
  buildDreamWeaverMergedVideoAssetMetadataContract,
  buildLocalMirrorAssetMetadataContract,
} from '../userAssetMetadataBuilders'

describe('userAssetMetadataBuilders', () => {
  it('builds local-mirror metadata and normalizes known local storage fields', () => {
    const metadata = buildLocalMirrorAssetMetadataContract(
      { module: 'asset_studio' },
      {
        local_storage_driver: 'OPFS',
        local_storage_path: ' local/cache/image-001 ',
        local_persist_level: 'PERSISTENT_REQUESTED',
      },
    )

    expect(metadata).toEqual({
      module: 'asset_studio',
      local_storage_driver: 'opfs',
      local_storage_path: 'local/cache/image-001',
      local_persist_level: 'persistent_requested',
    })
  })

  it('keeps scenario wrappers aligned with local-mirror metadata behavior', () => {
    const assetStudioMetadata = buildAssetStudioCollectedAssetMetadataContract(
      { scene: 'cover' },
      { local_storage_driver: 'OPFS' },
    )
    const audiobookMetadata = buildAudiobookChapterAudioAssetMetadataContract(
      { chapter_id: 12 },
      { local_storage_driver: 'OPFS' },
    )

    expect(assetStudioMetadata.local_storage_driver).toBe('opfs')
    expect(assetStudioMetadata.scene).toBe('cover')
    expect(audiobookMetadata.local_storage_driver).toBe('opfs')
    expect(audiobookMetadata.chapter_id).toBe(12)
  })

  it('builds dreamweaver library metadata with explicit fields overriding base metadata', () => {
    const metadata = buildDreamWeaverLibraryAssetMetadataContract({
      baseMetadata: {
        project_id: 1,
        entity_type: 'outdated',
        extra_flag: true,
      },
      projectId: 88,
      libraryAssetId: 'asset-001',
      libraryRole: 'reference',
      libraryUri: '/library/asset-001',
      entityType: 'character',
      entityId: 'char-7',
      view: 'front',
      approved: true,
    })

    expect(metadata).toEqual({
      project_id: 88,
      entity_type: 'character',
      extra_flag: true,
      library_asset_id: 'asset-001',
      library_role: 'reference',
      library_uri: '/library/asset-001',
      entity_id: 'char-7',
      view: 'front',
      approved: true,
    })
  })

  it('builds dreamweaver merged-video metadata with stable key names', () => {
    const metadata = buildDreamWeaverMergedVideoAssetMetadataContract({
      runId: 'run-123',
      projectId: 42,
      projectTitle: '项目 A',
      mergedVideoPath: '/tmp/merged.mp4',
    })

    expect(metadata).toEqual({
      run_id: 'run-123',
      project_id: 42,
      project_title: '项目 A',
      merged_video_path: '/tmp/merged.mp4',
    })
  })
})
