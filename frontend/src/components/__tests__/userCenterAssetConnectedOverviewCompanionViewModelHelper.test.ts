import { describe, expect, it, vi } from 'vitest'

import { buildUserCenterAssetConnectedOverviewCompanionViewModel } from '../user-assets/userCenterAssetConnectedOverviewCompanionViewModelHelper'

describe('userCenterAssetConnectedOverviewCompanionViewModelHelper', () => {
  it('composes strategy and points rules companion content options together', () => {
    const formatPointsValueLabel = vi.fn((value: number) => `M${value}`)
    const formatUpdatedAtLabel = vi.fn((value: string) => `DATE(${value})`)
    const getSourceLabel = vi.fn(() => '后台规则快照')

    const viewModel = buildUserCenterAssetConnectedOverviewCompanionViewModel({
      pointsRules: {
        reusable_asset_reward: 1,
        deliverable_asset_reward: 2,
        audiobook_completion_reward: 3,
        dreamweaver_completion_reward: 4,
        running_audiobook_frozen: 5,
        running_dreamweaver_frozen: 6,
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

    expect(viewModel.strategyCompanionContentOptions).toEqual({
      items: [
        '过程态资产继续保留在生成模块，避免用户中心承接复杂上下文操作。',
        '稳定素材、成片和跨模块复用结果进入用户中心，便于统一检索、标记和权益联动。',
        '不同类型资产采取不同策略，生成链路负责生产，用户中心负责汇总与治理。',
      ],
    })
    expect(viewModel.pointsRulesCompanionContentOptions).toEqual({
      content: expect.objectContaining({
        sourceLabel: '后台规则快照',
        updatedAtLabel: '最近更新：DATE(2026-04-24T00:00:00Z)',
        updatedByLabel: '最近操作人：ops',
      }),
      emptyText: '暂无可展示的积分规则快照。',
    })
  })

  it('preserves points rules empty state through the composed helper', () => {
    const viewModel = buildUserCenterAssetConnectedOverviewCompanionViewModel({
      pointsRules: null,
      formatPointsValueLabel: (value) => `${value}`,
      formatUpdatedAtLabel: (value) => value,
      getSourceLabel: () => '默认规则',
    })

    expect(viewModel.strategyCompanionContentOptions.items).toHaveLength(3)
    expect(viewModel.pointsRulesCompanionContentOptions).toEqual({
      content: null,
      emptyText: '暂无可展示的积分规则快照。',
    })
  })
})
