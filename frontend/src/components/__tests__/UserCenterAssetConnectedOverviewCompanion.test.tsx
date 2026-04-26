import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import {
  buildUserCenterAssetConnectedOverviewPointsRulesCompanionContent,
  buildUserCenterAssetConnectedOverviewStrategyCompanionContent,
  UserCenterAssetConnectedOverviewPointsRulesCompanionContent,
  UserCenterAssetConnectedOverviewStrategyCompanionContent,
} from '../user-assets/UserCenterAssetConnectedOverviewCompanion'

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

describe('UserCenterAssetConnectedOverviewCompanion', () => {
  it('builds strategy companion content through the shared builder', () => {
    const options = {
      items: [
        '过程态资产继续保留在生成模块。',
        '稳定素材进入用户中心统一检索。',
      ],
    }

    const slot = buildUserCenterAssetConnectedOverviewStrategyCompanionContent(options)

    expect(slot.type).toBe(UserCenterAssetConnectedOverviewStrategyCompanionContent)
    expect(slot.props).toEqual(options)
  })

  it('renders numbered strategy companion items', () => {
    const text = extractVisibleText(renderToStaticMarkup(
      <UserCenterAssetConnectedOverviewStrategyCompanionContent
        items={[
          '过程态资产继续保留在生成模块。',
          '稳定素材进入用户中心统一检索。',
        ]}
      />,
    ))

    expect(text).toContain('1. 过程态资产继续保留在生成模块。')
    expect(text).toContain('2. 稳定素材进入用户中心统一检索。')
  })

  it('builds and renders points rules companion content', () => {
    const options = {
      content: {
        sourceLabel: '后台规则快照',
        sourceColor: 'primary' as const,
        updatedAtLabel: '最近更新：2026-04-24 00:00',
        description: '这里展示当前积分模型实际采用的奖励、冻结和过期规则。',
        summaryItems: [
          { label: '复用资产奖励', value: '2 积分' },
          { label: '奖励有效期', value: '30 天' },
        ],
        updatedByLabel: '最近操作人：系统默认',
      },
      emptyText: '暂无可展示的积分规则快照。',
    }

    const slot = buildUserCenterAssetConnectedOverviewPointsRulesCompanionContent(options)
    const text = extractVisibleText(renderToStaticMarkup(
      <UserCenterAssetConnectedOverviewPointsRulesCompanionContent {...options} />,
    ))

    expect(slot.type).toBe(UserCenterAssetConnectedOverviewPointsRulesCompanionContent)
    expect(slot.props).toEqual(options)
    expect(text).toContain('后台规则快照')
    expect(text).toContain('最近更新：2026-04-24 00:00')
    expect(text).toContain('复用资产奖励')
    expect(text).toContain('2 积分')
    expect(text).toContain('最近操作人：系统默认')
  })

  it('renders points rules companion empty state', () => {
    const text = extractVisibleText(renderToStaticMarkup(
      <UserCenterAssetConnectedOverviewPointsRulesCompanionContent
        content={null}
        emptyText="暂无可展示的积分规则快照。"
      />,
    ))

    expect(text).toContain('暂无可展示的积分规则快照。')
  })
})
