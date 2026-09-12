import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import {
  buildUserAssetFilterToolbarPresentation,
  isUserAssetArchiveFilter,
  isUserAssetViewFilter,
} from '../user-assets/userAssetFilterToolbarPresentation'

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userAssetFilterToolbarPresentation', () => {
  it('builds filter fields, result summary and refresh action', () => {
    const presentation = buildUserAssetFilterToolbarPresentation({
      filters: {
        viewFilter: 'favorites',
        kindFilter: 'image',
        sourceFilter: 'dreamweaver_run',
        archiveFilter: 'archived',
        tagFilter: '角色',
      },
      kindOptions: ['image', 'video'],
      sourceOptions: [{ value: 'dreamweaver_run', label: '短剧成片' }],
      tagOptions: ['角色', '成片'],
      filteredCount: 12,
      loading: true,
    }, t)

    expect(presentation.fields.map((field) => field.key)).toEqual([
      'viewFilter',
      'kindFilter',
      'sourceFilter',
      'archiveFilter',
      'tagFilter',
    ])
    expect(presentation.fields[0]).toMatchObject({
      key: 'viewFilter',
      label: '资产视角',
      value: 'favorites',
    })
    expect(presentation.fields[0].options.slice(0, 2)).toEqual([
      { value: 'all', label: '全部资产' },
      { value: 'favorites', label: '仅看重点' },
    ])
    expect(presentation.fields[1].options).toEqual([
      { value: 'all', label: '全部类型' },
      { value: 'image', label: 'image' },
      { value: 'video', label: 'video' },
    ])
    expect(presentation.fields[2].options).toEqual([
      { value: 'all', label: '全部来源' },
      { value: 'dreamweaver_run', label: '短剧成片' },
    ])
    expect(presentation.fields[3]).toMatchObject({
      key: 'archiveFilter',
      label: '归档范围',
      value: 'archived',
    })
    expect(presentation.fields[4].options).toEqual([
      { value: 'all', label: '全部标签' },
      { value: '角色', label: '角色' },
      { value: '成片', label: '成片' },
    ])
    expect(presentation.resultLabel).toBe('当前结果 12')
    expect(presentation.refreshLabel).toBe('刷新资产')
    expect(presentation.refreshDisabled).toBe(true)
  })

  it('validates view and archive filter values', () => {
    expect(isUserAssetViewFilter('favorites')).toBe(true)
    expect(isUserAssetViewFilter('unknown')).toBe(false)
    expect(isUserAssetArchiveFilter('active')).toBe(true)
    expect(isUserAssetArchiveFilter('unknown')).toBe(false)
  })
})
