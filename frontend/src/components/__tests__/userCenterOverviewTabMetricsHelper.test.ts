import { describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import {
  buildUserCenterOverviewTabMetrics,
  buildUserCenterOverviewTabPointsAccountStatusMeta,
  buildUserCenterOverviewTabPricingPolicyPresentation,
} from '../user-assets/userCenterOverviewTabMetricsHelper'

describe('userCenterOverviewTabMetricsHelper', () => {
  it('builds points account status meta for partial and planned states', () => {
    expect(buildUserCenterOverviewTabPointsAccountStatusMeta('partial')).toEqual({
      label: 'userCenter.points.statusConnectedLedger',
      description: 'userCenter.points.statusConnectedLedgerDesc',
      color: 'info',
    })

    expect(buildUserCenterOverviewTabPointsAccountStatusMeta('planned')).toEqual({
      label: 'userCenter.points.statusGradual',
      description: 'userCenter.points.statusGradualDesc',
      color: 'warning',
    })
  })

  it('localizes points account status meta when a translator is provided', () => {
    const translate = ((key: string) => `T:${key}`) as TFunction
    expect(buildUserCenterOverviewTabPointsAccountStatusMeta('partial', translate)).toEqual({
      label: 'T:userCenter.points.statusConnectedLedger',
      description: 'T:userCenter.points.statusConnectedLedgerDesc',
      color: 'info',
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
      sourceLabel: 'userCenter.points.sourceAdmin',
      userPriceBasisLabel: 'userCenter.points.priceBasisTemplate',
      description: 'userCenter.points.pricingPolicyDescription',
      summaryItems: [
        { label: 'userCenter.points.exchangeRate', value: 'userCenter.points.exchangeRateValue' },
        { label: 'userCenter.points.pricingBasis', value: '公开价' },
        { label: 'userCenter.points.pricingRate', value: 'userCenter.points.pricingRateValue' },
        { label: 'userCenter.points.freezeBuffer', value: '25%' },
      ],
      updatedAtLabel: 'userCenter.points.adjustedAt',
    })
  })

  it('localizes pricing policy presentation when a translator is provided', () => {
    const translate = ((key: string) => `T:${key}`) as TFunction
    const presentation = buildUserCenterOverviewTabPricingPolicyPresentation({
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
      getPricingBasisLabel: (basis) => basis === 'public_list_price' ? 'userCenter.points.basisPublic' : 'userCenter.points.basisInternal',
      formatPercentRate: (value) => `${Number(value || 0) * 100}%`,
      formatUpdatedAtLabel: (value) => `FMT(${value})`,
      t: translate,
    })
    expect(presentation?.sourceLabel).toBe('T:userCenter.points.sourceAdmin')
    expect(presentation?.userPriceBasisLabel).toBe('T:userCenter.points.priceBasisTemplate')
    expect(presentation?.summaryItems[1].value).toBe('T:userCenter.points.basisPublic')
    expect(presentation?.updatedAtLabel).toBe('T:userCenter.points.adjustedAt')
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
        label: 'userCenter.points.statusGradual',
        description: 'userCenter.points.statusGradualDesc',
        color: 'warning',
      },
      pricingPolicyPresentation: null,
    })
  })
})
