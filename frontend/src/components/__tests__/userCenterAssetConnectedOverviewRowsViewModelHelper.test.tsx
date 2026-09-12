import { beforeAll, describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import { buildUserCenterAssetConnectedOverviewRowsViewModel } from '../user-assets/userCenterAssetConnectedOverviewRowsViewModelHelper'

function extractVisibleText(markup: string): string {
  return markup
    .replace(/<style[^>]*>[\s\S]*?<\/style>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userCenterAssetConnectedOverviewRowsViewModelHelper', () => {
  it('composes shared row slot options for strategy and points rules', () => {
    const viewModel = buildUserCenterAssetConnectedOverviewRowsViewModel({
      overviewBridge: {
        sectionProps: {
          items: [],
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

    expect(viewModel.strategyRowSlotOptions).toEqual({
      overviewBridge: {
        sectionProps: {
          items: [],
        },
      },
      companionTitle: '资产接入策略',
      companionContent: expect.any(Object),
    })
    expect(viewModel.pointsRulesRowSlotOptions).toEqual({
      overviewBridge: {
        sectionProps: {
          items: [],
        },
      },
      companionTitle: '当前积分规则',
      companionContent: expect.any(Object),
    })
    expect(extractVisibleText(renderToStaticMarkup(viewModel.strategyRowSlotOptions.companionContent))).toContain('策略内容')
    expect(extractVisibleText(renderToStaticMarkup(viewModel.pointsRulesRowSlotOptions.companionContent))).toContain('规则内容')
  })
})
