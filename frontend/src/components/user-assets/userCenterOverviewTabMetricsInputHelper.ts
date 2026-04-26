import type {
  UserCenterPointsAccount,
  UserCenterPointsOverviewResponse,
  UserCenterPointsPricingPolicyOverview,
} from '@/services/api'

export type UserCenterOverviewTabMetricsPointsOverviewInput = Pick<
  UserCenterPointsOverviewResponse,
  'points_account' | 'pricing_policy'
>

export type UserCenterOverviewTabMetricsInput = {
  connectedLedgerSourceCount: number
  pendingLedgerSourceCount: number
  pointsAccountStatus: UserCenterPointsAccount['status']
  pointsAccountBalance: number | null
  pointsAccountFrozen: number | null
  pointsAccountExpiringSoon: number | null
  pricingPolicy: UserCenterPointsPricingPolicyOverview | null
}

export type BuildUserCenterOverviewTabMetricsInputOptions = {
  pointsOverview?: UserCenterOverviewTabMetricsPointsOverviewInput | null
  pendingLedgerSignalCount: number
}

export function buildUserCenterOverviewTabMetricsInput(
  options: BuildUserCenterOverviewTabMetricsInputOptions,
): UserCenterOverviewTabMetricsInput {
  const pointsAccount = options.pointsOverview?.points_account

  return {
    connectedLedgerSourceCount: pointsAccount?.connected_source_count ?? 0,
    pendingLedgerSourceCount: pointsAccount?.pending_source_count ?? options.pendingLedgerSignalCount,
    pointsAccountStatus: pointsAccount?.status ?? 'planned',
    pointsAccountBalance: pointsAccount?.balance ?? null,
    pointsAccountFrozen: pointsAccount?.frozen ?? null,
    pointsAccountExpiringSoon: pointsAccount?.expiring_soon ?? null,
    pricingPolicy: options.pointsOverview?.pricing_policy ?? null,
  }
}
