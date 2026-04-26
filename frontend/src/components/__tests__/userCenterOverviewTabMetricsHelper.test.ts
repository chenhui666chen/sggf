import { describe, expect, it } from 'vitest'

import {
  buildUserCenterOverviewTabMetrics,
  buildUserCenterOverviewTabPointsAccountStatusMeta,
  buildUserCenterOverviewTabPricingPolicyPresentation,
} from '../user-assets/userCenterOverviewTabMetricsHelper'

describe('userCenterOverviewTabMetricsHelper', () => {
  it('builds points account status meta for partial and planned states', () => {
    expect(buildUserCenterOverviewTabPointsAccountStatusMeta('partial')).toEqual({
      label: '已接入账本',
      description: '已有真实积分账本与任务计费链路接入用户中心，后续会继续扩展更多消费和权益来源。',
      color: 'info',
    })

    expect(buildUserCenterOverviewTabPointsAccountStatusMeta('planned')).toEqual({
      label: '逐步扩展',
      description: '积分账户结构已就绪，当前已支持积分预检和部分任务计费，更多权益与消费来源会继续接入。',
      color: 'warning',
    })
  })

  it('builds pricing policy presentation from shared formatting helpers', () => {
    expect(buildUserCenterOverviewTabPricingPolicyPresentation({
      pricingPolicy: {
        points_per_yuan: 100,
        user_price_basis: 'public_list_price',
        user_price_rate: 1.5,
        freeze_buffer_rate: 0.25,
        source: 'admin_log',
        updated_at: '2026-04-24T00:00:00Z',
        updated_by_user_id: 1,
        updated_by_username: 'ops',
      },
      getPricingBasisLabel: (basis) => basis === 'public_list_price' ? '公开价' : '标准价',
      formatPercentRate: (value) => `${Number(value || 0) * 100}%`,
      formatUpdatedAtLabel: (value) => `FMT(${value})`,
    })).toEqual({
      sourceColor: 'primary',
      sourceLabel: '后台定价快照',
      userPriceBasisLabel: '用户按 公开价 计点',
      description: '用户侧按公开价或内部标准价折算积分，不额外加价；运行中任务会按当前缓冲比例预留建议冻结值。',
      summaryItems: [
        { label: '积分汇率', value: '1 元 = 100 积分' },
        { label: '用户计价基准', value: '公开价' },
        { label: '用户计价系数', value: '1.50 ×' },
        { label: '冻结缓冲', value: '25%' },
      ],
      updatedAtLabel: '最近调整：FMT(2026-04-24T00:00:00Z)',
    })
  })

  it('composes overview tab metrics and preserves empty pricing policy state', () => {
    expect(buildUserCenterOverviewTabMetrics({
      pointsAccountStatus: 'planned',
      pricingPolicy: null,
      getPricingBasisLabel: () => '默认',
      formatPercentRate: (value) => `${value}`,
      formatUpdatedAtLabel: (value) => value,
    })).toEqual({
      pointsAccountStatusMeta: {
        label: '逐步扩展',
        description: '积分账户结构已就绪，当前已支持积分预检和部分任务计费，更多权益与消费来源会继续接入。',
        color: 'warning',
      },
      pricingPolicyPresentation: null,
    })
  })
})
