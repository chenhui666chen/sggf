import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'
import type { UserAssetSourceInfo } from '@/contracts/userAssetSourceReaders'
import type { UserAssetRecord } from '@/services/api'

import { buildUserAssetCardPresentation } from '../user-assets/userAssetCardPresentation'

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

function createSourceInfo(overrides: Partial<UserAssetSourceInfo> = {}): UserAssetSourceInfo {
  return {
    label: '资产工坊',
    summary: '来自资产工坊。',
    traceLabel: null,
    projectLabel: null,
    backPath: null,
    backLabel: null,
    ...overrides,
  }
}

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userAssetCardPresentation', () => {
  it('builds header chips, description and action labels', () => {
    const presentation = buildUserAssetCardPresentation(
      createUserAssetRecord({
        id: 7,
        asset_kind: 'video',
        asset_class: 'deliverable',
        description: '  成片交付版本  ',
        is_favorite: true,
        archived_at: '2026-04-23T00:00:00Z',
      }),
      createSourceInfo({
        label: '短剧成片',
      }),
      {
        createdAtLabel: '2026/04/23 10:00:00',
      },
      t,
    )

    expect(presentation.headerChips).toEqual([
      { key: 'asset-kind-7', label: 'video' },
      { key: 'asset-class-7', label: '成品资产', color: 'warning' },
      { key: 'asset-source-7', label: '来源：短剧成片', variant: 'outlined' },
      { key: 'asset-favorite-7', label: '重点资产', color: 'primary' },
      { key: 'asset-archived-7', label: '已归档', variant: 'outlined' },
    ])
    expect(presentation.description).toBe('成片交付版本')
    expect(presentation.createdAtLabel).toBe('收录时间：2026/04/23 10:00:00')
    expect(presentation.clearLocalAction).toEqual({ label: '清理本地副本' })
    expect(presentation.favoriteAction.label).toBe('取消重点')
    expect(presentation.archiveAction.label).toBe('恢复活跃')
  })

  it('builds detail chips from source info and first three tags', () => {
    const presentation = buildUserAssetCardPresentation(
      createUserAssetRecord({
        id: 9,
        tags: ['角色', '正面', '高清', '应被忽略'],
      }),
      createSourceInfo({
        projectLabel: '海城剧场',
        traceLabel: '角色 · 正面',
        backPath: '/drama/3/library',
        backLabel: '前往素材库',
      }),
      {
        createdAtLabel: '2026/04/23 10:00:00',
        hasLocalObjectUrl: true,
      },
      t,
    )

    expect(presentation.detailChips).toEqual([
      { key: 'asset-project-9', label: '海城剧场', variant: 'outlined' },
      { key: 'asset-trace-9', label: '角色 · 正面', variant: 'outlined' },
      { key: 'asset-tag-9-角色', label: '角色', variant: 'outlined' },
      { key: 'asset-tag-9-正面', label: '正面', variant: 'outlined' },
      { key: 'asset-tag-9-高清', label: '高清', variant: 'outlined' },
    ])
    expect(presentation.sourceAction).toEqual({
      label: '前往素材库',
      path: '/drama/3/library',
    })
  })

  it('falls back to default description and hides local cleanup for non local mirror assets', () => {
    const presentation = buildUserAssetCardPresentation(
      createUserAssetRecord({
        id: 11,
        storage_mode: 'durable_cloud',
        description: '   ',
      }),
      createSourceInfo(),
      {
        createdAtLabel: '2026/04/23 10:00:00',
      },
      t,
    )

    expect(presentation.description).toBe('当前资产尚未补充说明，可以在用户中心内完善标题、描述和标签。')
    expect(presentation.sourceAction).toBeNull()
    expect(presentation.clearLocalAction).toBeNull()
    expect(presentation.editAction.label).toBe('编辑信息')
    expect(presentation.favoriteAction.label).toBe('设为重点')
    expect(presentation.archiveAction.label).toBe('归档')
  })

  it('shows restore action and pending chip when local mirror asset has no local object url', () => {
    const presentation = buildUserAssetCardPresentation(
      createUserAssetRecord({
        id: 12,
        tags: ['角色'],
      }),
      createSourceInfo(),
      {
        createdAtLabel: '2026/04/23 10:00:00',
        hasLocalObjectUrl: false,
      },
      t,
    )

    expect(presentation.restoreLocalAction).toEqual({ label: '重新收录到本地' })
    expect(presentation.clearLocalAction).toEqual({ label: '清理本地副本' })
    expect(presentation.detailChips).toEqual(
      expect.arrayContaining([
        {
          key: 'asset-local-restore-12',
          label: '本地副本待恢复',
          color: 'warning',
        },
      ]),
    )
  })

  it('hides restore action when local object url already exists', () => {
    const presentation = buildUserAssetCardPresentation(
      createUserAssetRecord({
        id: 13,
      }),
      createSourceInfo(),
      {
        createdAtLabel: '2026/04/23 10:00:00',
        hasLocalObjectUrl: true,
      },
      t,
    )

    expect(presentation.restoreLocalAction).toBeNull()
    expect(presentation.detailChips.find((chip) => chip.key === 'asset-local-restore-13')).toBeUndefined()
  })
})
