import { useMemo } from 'react'

import {
  buildUserCenterOverviewTabMetrics,
  type BuildUserCenterOverviewTabMetricsOptions,
  type UserCenterOverviewTabMetrics,
} from '@/components/user-assets/userCenterOverviewTabMetricsHelper'
import {
  buildUserCenterOverviewTabMetricsInput,
  type BuildUserCenterOverviewTabMetricsInputOptions,
  type UserCenterOverviewTabMetricsInput,
} from '@/components/user-assets/userCenterOverviewTabMetricsInputHelper'

export type UserCenterOverviewTabMetricsFacade = Pick<
  UserCenterOverviewTabMetricsInput,
  | 'connectedLedgerSourceCount'
  | 'pendingLedgerSourceCount'
  | 'pointsAccountBalance'
  | 'pointsAccountFrozen'
  | 'pointsAccountExpiringSoon'
> & UserCenterOverviewTabMetrics

export type UseUserCenterOverviewTabMetricsOptions =
  BuildUserCenterOverviewTabMetricsInputOptions
  & Omit<BuildUserCenterOverviewTabMetricsOptions, 'pointsAccountStatus' | 'pricingPolicy'>

export function buildUserCenterOverviewTabMetricsFacade(options: {
  input: UserCenterOverviewTabMetricsInput
  metrics: UserCenterOverviewTabMetrics
}): UserCenterOverviewTabMetricsFacade {
  return {
    connectedLedgerSourceCount: options.input.connectedLedgerSourceCount,
    pendingLedgerSourceCount: options.input.pendingLedgerSourceCount,
    pointsAccountBalance: options.input.pointsAccountBalance,
    pointsAccountFrozen: options.input.pointsAccountFrozen,
    pointsAccountExpiringSoon: options.input.pointsAccountExpiringSoon,
    pointsAccountStatusMeta: options.metrics.pointsAccountStatusMeta,
    pricingPolicyPresentation: options.metrics.pricingPolicyPresentation,
  }
}

export function useUserCenterOverviewTabMetrics(
  options: UseUserCenterOverviewTabMetricsOptions,
): UserCenterOverviewTabMetricsFacade {
  const input = useMemo(
    () => buildUserCenterOverviewTabMetricsInput({
      pointsOverview: options.pointsOverview,
      pendingLedgerSignalCount: options.pendingLedgerSignalCount,
    }),
    [
      options.pointsOverview?.points_account,
      options.pointsOverview?.pricing_policy,
      options.pendingLedgerSignalCount,
    ],
  )

  const metrics = useMemo(
    () => buildUserCenterOverviewTabMetrics({
      pointsAccountStatus: input.pointsAccountStatus,
      pricingPolicy: input.pricingPolicy,
      getPricingBasisLabel: options.getPricingBasisLabel,
      formatPercentRate: options.formatPercentRate,
      formatUpdatedAtLabel: options.formatUpdatedAtLabel,
    }),
    [
      input.pointsAccountStatus,
      input.pricingPolicy,
      options.getPricingBasisLabel,
      options.formatPercentRate,
      options.formatUpdatedAtLabel,
    ],
  )

  return useMemo(
    () => buildUserCenterOverviewTabMetricsFacade({
      input,
      metrics,
    }),
    [input, metrics],
  )
}
