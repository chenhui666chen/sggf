import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import {
  buildUserCenterAssetConnectedOverviewItems,
  buildUserCenterAssetConnectedOverviewSectionProps,
} from '../user-assets/userCenterAssetConnectedOverviewPresentation'

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userCenterAssetConnectedOverviewPresentation', () => {
  it('builds connected overview items with user asset count and summary fields', () => {
    expect(buildUserCenterAssetConnectedOverviewItems({
      projectCount: 3,
      userAssetCount: 12,
      audiobookProjectCount: 5,
      totalAudiobookCostLabel: '¥12.00',
      dreamweaverRunCount: 9,
    }, t)).toEqual([
      { key: 'connected-project-count', label: '项目数', value: 3 },
      { key: 'connected-user-asset-count', label: '用户资产数', value: 12 },
      { key: 'connected-audiobook-project-count', label: '有声书项目数', value: 5 },
      { key: 'connected-audiobook-total-cost', label: '有声书累计成本', value: '¥12.00' },
      { key: 'connected-dreamweaver-run-count', label: '短剧运行次数', value: 9 },
    ])
  })

  it('builds section props with connected overview fallbacks', () => {
    expect(buildUserCenterAssetConnectedOverviewSectionProps({
      connectedProjectCount: null,
      fallbackProjectCount: 4,
      userAssetCount: 8,
      connectedAudiobookProjectCount: undefined,
      fallbackAudiobookProjectCount: 6,
      totalAudiobookCostLabel: '¥99.00',
      dreamweaverRunCount: 11,
    }, t)).toEqual({
      items: [
        { key: 'connected-project-count', label: '项目数', value: 4 },
        { key: 'connected-user-asset-count', label: '用户资产数', value: 8 },
        { key: 'connected-audiobook-project-count', label: '有声书项目数', value: 6 },
        { key: 'connected-audiobook-total-cost', label: '有声书累计成本', value: '¥99.00' },
        { key: 'connected-dreamweaver-run-count', label: '短剧运行次数', value: 11 },
      ],
    })
  })
})
