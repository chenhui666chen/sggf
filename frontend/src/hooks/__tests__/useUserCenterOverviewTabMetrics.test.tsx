import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import {
  buildUserCenterOverviewTabMetricsFacade,
  type UserCenterOverviewTabMetricsFacade,
  useUserCenterOverviewTabMetrics,
} from '../useUserCenterOverviewTabMetrics'

describe('useUserCenterOverviewTabMetrics', () => {
  it('builds a facade from overview-tab metrics input and presentation output', () => {
    expect(buildUserCenterOverviewTabMetricsFacade({
      input: {
        connectedLedgerSourceCount: 4,
        pendingLedgerSourceCount: 2,
        pointsAccountStatus: 'partial',
        pointsAccountBalance: 120,
        pointsAccountFrozen: 30,
        pointsAccountExpiringSoon: 12,
        pricingPolicy: null,
      },
      metrics: {
        pointsAccountStatusMeta: {
          label: '已接入账本',
          description: '说明',
          color: 'info',
        },
        pricingPolicyPresentation: null,
      },
    })).toEqual({
      connectedLedgerSourceCount: 4,
      pendingLedgerSourceCount: 2,
      pointsAccountBalance: 120,
      pointsAccountFrozen: 30,
      pointsAccountExpiringSoon: 12,
      pointsAccountStatusMeta: {
        label: '已接入账本',
        description: '说明',
        color: 'info',
      },
      pricingPolicyPresentation: null,
    })
  })

  it('adapts page-facing metrics input into reusable overview-tab facade output', () => {
    let capturedMetrics: UserCenterOverviewTabMetricsFacade | null = null

    function Harness() {
      capturedMetrics = useUserCenterOverviewTabMetrics({
        pointsOverview: {
          points_account: {
            balance: 120,
            frozen: 30,
            expiring_soon: 12,
            status: 'partial',
            connected_source_count: 4,
            pending_source_count: 2,
          },
          pricing_policy: {
            points_per_yuan: 100,
            user_price_basis: 'public_list_price',
            user_price_rate: 1.5,
            freeze_buffer_rate: 0.25,
            source: 'admin_log',
            updated_at: '2026-04-24T00:00:00Z',
            updated_by_user_id: 1,
            updated_by_username: 'ops',
          },
        },
        pendingLedgerSignalCount: 9,
        getPricingBasisLabel: (basis) => basis === 'public_list_price' ? '公开价' : '标准价',
        formatPercentRate: (value) => `${Number(value || 0) * 100}%`,
        formatUpdatedAtLabel: (value) => `FMT(${value})`,
      })

      return null
    }

    renderToStaticMarkup(<Harness />)

    if (!capturedMetrics) {
      throw new Error('expected metrics to be captured')
    }

    const metrics: UserCenterOverviewTabMetricsFacade = capturedMetrics

    expect(metrics.connectedLedgerSourceCount).toBe(4)
    expect(metrics.pendingLedgerSourceCount).toBe(2)
    expect(metrics.pointsAccountBalance).toBe(120)
    expect(metrics.pointsAccountStatusMeta).toEqual({
      label: '已接入账本',
      description: '已有真实积分账本与任务计费链路接入用户中心，后续会继续扩展更多消费和权益来源。',
      color: 'info',
    })
    expect(metrics.pricingPolicyPresentation).toEqual(expect.objectContaining({
      sourceLabel: '后台定价快照',
      updatedAtLabel: '最近调整：FMT(2026-04-24T00:00:00Z)',
    }))
  })
})
