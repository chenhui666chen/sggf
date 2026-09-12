import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import UserCenterAssetConnectedOverviewRow from '../user-assets/UserCenterAssetConnectedOverviewRow'
import { buildUserCenterAssetConnectedOverviewRows } from '../user-assets/userCenterAssetConnectedOverviewRowsHelper'

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userCenterAssetConnectedOverviewRowsHelper', () => {
  it('builds reusable strategy and points rules row slots from shared rows view model input', () => {
    const rows = buildUserCenterAssetConnectedOverviewRows({
      overviewBridge: {
        sectionProps: {
          items: [
            {
              key: 'connected-project-count',
              label: '项目数',
              value: 3,
            },
          ],
        },
      },
      companionViewModel: {
        strategyCompanionContentOptions: {
          items: ['策略内容'],
        },
        pointsRulesCompanionContentOptions: {
          content: {
            sourceLabel: '后台规则快照',
            sourceColor: 'primary',
            updatedAtLabel: '最近更新：2026-04-24 00:00',
            description: '规则内容',
            summaryItems: [],
            updatedByLabel: '最近操作人：系统默认',
          },
          emptyText: '暂无规则',
        },
      },
    }, t)

    expect(rows.strategyRowSlot.type).toBe(UserCenterAssetConnectedOverviewRow)
    expect(rows.pointsRulesRowSlot.type).toBe(UserCenterAssetConnectedOverviewRow)
    expect(rows.strategyRowSlot.props.companionTitle).toBe('资产接入策略')
    expect(rows.pointsRulesRowSlot.props.companionTitle).toBe('当前积分规则')
  })
})
