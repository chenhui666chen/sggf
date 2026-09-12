import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import type { UserAssetRecord } from '@/services/api'

import {
  buildActivateBatchUserAssetCommand,
  buildArchiveBatchUserAssetCommand,
  buildClearLocalCopyBatchUserAssetCommand,
  buildFavoriteBatchUserAssetCommand,
  buildUserAssetKindOptionsFromValues,
  buildToggleArchivedUserAssetCommand,
  buildToggleFavoriteUserAssetCommand,
  buildUserAssetKindOptions,
  buildUserAssetListSelectionState,
  buildUserAssetSourceOptionsFromSourceModules,
  buildUserAssetSourceOptions,
  buildUserAssetTagOptionsFromValues,
  buildUserAssetTagOptions,
  filterUserAssets,
  getUserAssetActionKey,
  pruneUserAssetSelection,
  toggleSelectAllUserAssets,
  toggleUserAssetSelection,
  type UserAssetListFilters,
} from '../user-assets/userAssetListPresentation'

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

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userAssetListPresentation', () => {
  it('builds kind, tag and source filter options', () => {
    const assets = [
      createUserAssetRecord({
        id: 1,
        asset_kind: 'image',
        source_module: 'asset_studio',
        tags: ['角色', '高清'],
      }),
      createUserAssetRecord({
        id: 2,
        asset_kind: 'video',
        source_module: 'dreamweaver_run',
        metadata_json: { run_id: 'run-22', project_id: 3 },
        tags: ['高清', '成片'],
      }),
    ]
    const projectTitleMap = new Map([[3, '海城剧场']])

    expect(buildUserAssetKindOptions(assets)).toEqual(['image', 'video'])
    expect(buildUserAssetTagOptions(assets)).toEqual(['成片', '高清', '角色'])
    expect(buildUserAssetSourceOptions(assets, projectTitleMap, t)).toEqual([
      { value: 'dreamweaver_run', label: '短剧成片' },
      { value: 'asset_studio', label: '资产工坊' },
    ])
    expect(buildUserAssetKindOptionsFromValues(['video', 'image', 'video'])).toEqual(['image', 'video'])
    expect(buildUserAssetTagOptionsFromValues(['角色', '成片', '角色'])).toEqual(['成片', '角色'])
    expect(buildUserAssetSourceOptionsFromSourceModules(['dreamweaver_run', 'asset_studio', 'dreamweaver_run'], t)).toEqual([
      { value: 'dreamweaver_run', label: '短剧成片' },
      { value: 'asset_studio', label: '资产工坊' },
    ])
  })

  it('filters assets by archive, view, kind, source and tag', () => {
    const assets = [
      createUserAssetRecord({
        id: 1,
        asset_kind: 'image',
        source_module: 'asset_studio',
        asset_class: 'reusable',
        is_favorite: true,
        tags: ['角色'],
      }),
      createUserAssetRecord({
        id: 2,
        asset_kind: 'video',
        source_module: 'dreamweaver_run',
        asset_class: 'deliverable',
        archived_at: '2026-04-23T00:00:00Z',
        tags: ['成片'],
      }),
    ]

    const filters: UserAssetListFilters = {
      viewFilter: 'favorites',
      kindFilter: 'image',
      archiveFilter: 'active',
      sourceFilter: 'asset_studio',
      tagFilter: '角色',
    }
    expect(filterUserAssets(assets, filters).map((asset) => asset.id)).toEqual([1])
  })

  it('builds selection state and selection mutation helpers', () => {
    const visibleAssets = [
      createUserAssetRecord({ id: 1 }),
      createUserAssetRecord({ id: 2, storage_mode: 'durable_cloud' }),
      createUserAssetRecord({ id: 3 }),
    ]

    const selection = buildUserAssetListSelectionState(visibleAssets, [1, 2, 3])

    expect(selection.selectedAssetIds).toEqual([1, 2, 3])
    expect(Array.from(selection.selectedAssetIdSet)).toEqual([1, 2, 3])
    expect(selection.selectedAssets.map((asset) => asset.id)).toEqual([1, 2, 3])
    expect(selection.selectedCount).toBe(3)
    expect(selection.selectedLocalMirrorCount).toBe(2)
    expect(selection.visibleCount).toBe(3)
    expect(selection.hasSelection).toBe(true)
    expect(selection.allVisibleSelected).toBe(true)
    expect(pruneUserAssetSelection([1, 4], visibleAssets)).toEqual([1])
    expect(toggleUserAssetSelection([1, 3], 3)).toEqual([1])
    expect(toggleUserAssetSelection([1], 2)).toEqual([1, 2])
    expect(toggleSelectAllUserAssets(visibleAssets, false)).toEqual([1, 2, 3])
    expect(toggleSelectAllUserAssets(visibleAssets, true)).toEqual([])
  })

  it('builds single-asset and batch action commands', () => {
    const favoriteCommand = buildToggleFavoriteUserAssetCommand(
      createUserAssetRecord({ id: 7, is_favorite: false }),
      t,
    )
    const archiveCommand = buildToggleArchivedUserAssetCommand(
      createUserAssetRecord({ id: 8, archived_at: '2026-04-23T00:00:00Z' }),
      t,
    )

    expect(getUserAssetActionKey(7)).toBe('asset-7')
    expect(favoriteCommand).toEqual({
      actionKey: 'asset-7',
      payload: { is_favorite: true },
      successText: '已设为重点资产',
    })
    expect(archiveCommand).toEqual({
      actionKey: 'asset-8',
      payload: { archived: false },
      successText: '已恢复为活跃资产',
    })
    expect(buildFavoriteBatchUserAssetCommand(t)).toEqual({
      kind: 'remote_update',
      label: '设为重点',
      payload: { is_favorite: true },
      successText: '已批量设为重点',
    })
    expect(buildArchiveBatchUserAssetCommand(t)).toEqual({
      kind: 'remote_update',
      label: '归档',
      payload: { archived: true },
      successText: '已批量归档',
    })
    expect(buildActivateBatchUserAssetCommand(t)).toEqual({
      kind: 'remote_update',
      label: '恢复活跃',
      payload: { archived: false },
      successText: '已批量恢复为活跃',
    })
    expect(buildClearLocalCopyBatchUserAssetCommand(t)).toEqual({
      kind: 'clear_local_copy',
      label: '清理本地副本',
      successText: '已批量清理本地副本',
    })
  })
})
