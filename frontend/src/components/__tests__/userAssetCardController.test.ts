import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'
import type { UserAssetRecord } from '@/services/api'

import {
  buildUserAssetCardController,
  formatUserAssetCardDateTime,
} from '../user-assets/userAssetCardController'

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

describe('userAssetCardController', () => {
  it('builds card key, commands and selection state', () => {
    const controller = buildUserAssetCardController(
      createUserAssetRecord({
        id: 7,
        is_favorite: true,
        archived_at: '2026-04-23T00:00:00Z',
      }),
      {
        assetActionKey: 'asset-7',
        selectedAssetIdSet: new Set([7]),
      },
      t,
    )

    expect(controller.cardKey).toBe('user-asset-7')
    expect(controller.isSelected).toBe(true)
    expect(controller.isSubmitting).toBe(true)
    expect(controller.favoriteCommand).toEqual({
      actionKey: 'asset-7',
      payload: { is_favorite: false },
      successText: '已取消重点资产',
    })
    expect(controller.archiveCommand).toEqual({
      actionKey: 'asset-7',
      payload: { archived: false },
      successText: '已恢复为活跃资产',
    })
    expect(controller.createdAtLabel).toMatch(/^.+$/)
    expect(controller.createdAtLabel).not.toBe('暂无时间')
  })

  it('falls back to default time label for invalid timestamps', () => {
    expect(formatUserAssetCardDateTime(undefined, undefined, t)).toBe('暂无时间')
    expect(formatUserAssetCardDateTime('invalid-date', undefined, t)).toBe('暂无时间')
    expect(buildUserAssetCardController(createUserAssetRecord({ created_at: '' }), {}, t).createdAtLabel).toBe('暂无时间')
  })

  it('renders the timestamp in whichever language it is told to', () => {
    // 卡片时间不再写死 zh-CN：由调用方把当前语言穿进来。
    const sample = '2026-03-15T08:30:45Z'

    expect(formatUserAssetCardDateTime(sample, 'zh-CN')).toContain('年')
    expect(formatUserAssetCardDateTime(sample, 'en-US')).toContain('Mar')
  })

  it('passes the locale through the card controller', () => {
    const controller = buildUserAssetCardController(
      createUserAssetRecord({ created_at: '2026-03-15T08:30:45Z' }),
      { locale: 'en-US' },
    )

    expect(controller.createdAtLabel).toContain('Mar')
  })
})
