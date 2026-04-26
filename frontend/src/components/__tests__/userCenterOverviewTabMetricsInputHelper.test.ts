import { describe, expect, it } from 'vitest'

import { buildUserCenterOverviewTabMetricsInput } from '../user-assets/userCenterOverviewTabMetricsInputHelper'

describe('userCenterOverviewTabMetricsInputHelper', () => {
  it('builds overview-tab metrics input from points overview and pending ledger fallback', () => {
    expect(buildUserCenterOverviewTabMetricsInput({
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
    })).toEqual({
      connectedLedgerSourceCount: 4,
      pendingLedgerSourceCount: 2,
      pointsAccountStatus: 'partial',
      pointsAccountBalance: 120,
      pointsAccountFrozen: 30,
      pointsAccountExpiringSoon: 12,
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
    })
  })

  it('uses planned/null defaults when points overview is unavailable', () => {
    expect(buildUserCenterOverviewTabMetricsInput({
      pointsOverview: null,
      pendingLedgerSignalCount: 5,
    })).toEqual({
      connectedLedgerSourceCount: 0,
      pendingLedgerSourceCount: 5,
      pointsAccountStatus: 'planned',
      pointsAccountBalance: null,
      pointsAccountFrozen: null,
      pointsAccountExpiringSoon: null,
      pricingPolicy: null,
    })
  })
})
