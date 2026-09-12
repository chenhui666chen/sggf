import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import {
  buildUserAssetListFeedbackCopy,
  buildUserAssetOverviewMetricSpecs,
} from '../user-assets/userAssetOverviewPresentation'

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userAssetOverviewPresentation', () => {
  it('builds overview metrics with stable labels and values', () => {
    expect(
      buildUserAssetOverviewMetricSpecs({
        activeAssetCount: 8,
        reusableAssetCount: 5,
        deliverableAssetCount: 3,
        favoriteAssetCount: 2,
        archivedAssetCount: 4,
      },
      t,
    ),
    ).toEqual([
      {
        key: 'active-assets',
        title: '活跃资产',
        value: 8,
        helper: '用户中心负责汇总、筛选和归档，不替代模块内工作台。',
        color: '#2563eb',
      },
      {
        key: 'reusable-assets',
        title: '可复用素材',
        value: '5 / 3',
        helper: '优先沉淀可跨项目复用的稳定素材。',
        color: '#7c3aed',
      },
      {
        key: 'favorite-archived-assets',
        title: '重点 / 归档',
        value: '2 / 4',
        helper: '重点资产用于快速复用，归档资产用于沉淀历史成果。',
        color: '#f97316',
      },
    ])
  })

  it('builds list feedback copy', () => {
    expect(buildUserAssetListFeedbackCopy(t)).toEqual({
      emptyCollectionMessage: '还没有收录到用户中心的资产，后续可以从各生成模块纳入稳定成果。',
      emptyFilterMessage: '当前筛选条件下没有匹配资产，可以切换筛选项查看其他结果。',
    })
  })
})
