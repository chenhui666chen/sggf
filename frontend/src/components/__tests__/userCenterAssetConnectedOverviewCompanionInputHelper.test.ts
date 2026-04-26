import { describe, expect, it, vi } from 'vitest'

import {
  buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput,
  buildUserCenterAssetConnectedOverviewStrategyCompanionContentOptionsFromInput,
} from '../user-assets/userCenterAssetConnectedOverviewCompanionInputHelper'

describe('userCenterAssetConnectedOverviewCompanionInputHelper', () => {
  it('builds shared strategy companion items without page-local literals', () => {
    expect(buildUserCenterAssetConnectedOverviewStrategyCompanionContentOptionsFromInput()).toEqual({
      items: [
        '过程态资产继续保留在生成模块，避免用户中心承接复杂上下文操作。',
        '稳定素材、成片和跨模块复用结果进入用户中心，便于统一检索、标记和权益联动。',
        '不同类型资产采取不同策略，生成链路负责生产，用户中心负责汇总与治理。',
      ],
    })
  })

  it('adapts points rules into shared companion content options', () => {
    const formatPointsValueLabel = vi.fn((value: number) => `P${value.toFixed(1)}`)
    const formatUpdatedAtLabel = vi.fn((value: string) => `FMT(${value})`)
    const getSourceLabel = vi.fn(() => '后台规则快照')

    const options = buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput({
      pointsRules: {
        reusable_asset_reward: 2,
        deliverable_asset_reward: 4,
        audiobook_completion_reward: 6,
        dreamweaver_completion_reward: 8,
        running_audiobook_frozen: 10,
        running_dreamweaver_frozen: 12,
        reward_ttl_days: 30,
        expiring_notice_days: 7,
        source: 'admin_log',
        updated_at: '2026-04-24T00:00:00Z',
        updated_by_user_id: 1,
        updated_by_username: 'ops',
      },
      formatPointsValueLabel,
      formatUpdatedAtLabel,
      getSourceLabel,
    })

    expect(formatPointsValueLabel).toHaveBeenCalledWith(2)
    expect(formatPointsValueLabel).toHaveBeenCalledWith(12)
    expect(formatUpdatedAtLabel).toHaveBeenCalledWith('2026-04-24T00:00:00Z')
    expect(getSourceLabel).toHaveBeenCalledWith('admin_log')
    expect(options).toEqual({
      content: {
        sourceLabel: '后台规则快照',
        sourceColor: 'primary',
        updatedAtLabel: '最近更新：FMT(2026-04-24T00:00:00Z)',
        description: '这里展示当前积分模型实际采用的奖励、冻结和过期规则。',
        summaryItems: [
          { label: '复用资产奖励', value: 'P2.0 积分' },
          { label: '交付资产奖励', value: 'P4.0 积分' },
          { label: '有声书完成奖励', value: 'P6.0 积分' },
          { label: '短剧完成奖励', value: 'P8.0 积分' },
          { label: '有声书运行冻结', value: 'P10.0 积分' },
          { label: '短剧运行冻结', value: 'P12.0 积分' },
          { label: '奖励有效期', value: '30 天' },
          { label: '到期提醒窗口', value: '7 天' },
        ],
        updatedByLabel: '最近操作人：ops',
      },
      emptyText: '暂无可展示的积分规则快照。',
    })
  })

  it('keeps points rules companion empty state when rules are unavailable', () => {
    expect(buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput({
      pointsRules: null,
      formatPointsValueLabel: (value) => `${value}`,
      formatUpdatedAtLabel: (value) => value,
      getSourceLabel: () => '默认规则',
    })).toEqual({
      content: null,
      emptyText: '暂无可展示的积分规则快照。',
    })
  })
})
