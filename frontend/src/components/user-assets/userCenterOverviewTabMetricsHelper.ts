import type { TFunction } from 'i18next'

import type {
  UserCenterPointsAccount,
  UserCenterPointsPricingPolicyOverview,
} from '@/services/api'

export type UserCenterOverviewTabPointsAccountStatusMeta = {
  label: string
  description: string
  color: 'info' | 'warning'
}

export type UserCenterOverviewTabSummaryItem = {
  label: string
  value: string
}

export type UserCenterOverviewTabPricingPolicyPresentation = {
  sourceColor: 'default' | 'primary'
  sourceLabel: string
  userPriceBasisLabel: string
  description: string
  summaryItems: UserCenterOverviewTabSummaryItem[]
  updatedAtLabel: string
}

export type UserCenterOverviewTabMetrics = {
  pointsAccountStatusMeta: UserCenterOverviewTabPointsAccountStatusMeta
  pricingPolicyPresentation: UserCenterOverviewTabPricingPolicyPresentation | null
}

export type BuildUserCenterOverviewTabMetricsOptions = {
  pointsAccountStatus?: UserCenterPointsAccount['status'] | null
  pricingPolicy?: UserCenterPointsPricingPolicyOverview | null
  getPricingBasisLabel: (basis?: UserCenterPointsPricingPolicyOverview['user_price_basis'] | null) => string
  formatPercentRate: (value?: number | null) => string
  formatUpdatedAtLabel: (value: string) => string
  /** 可选翻译函数：缺省时原样返回 key（便于测试与纯计算场景）。 */
  t?: TFunction
}

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export function buildUserCenterOverviewTabPointsAccountStatusMeta(
  pointsAccountStatus?: UserCenterPointsAccount['status'] | null,
  t?: TFunction,
): UserCenterOverviewTabPointsAccountStatusMeta {
  const translate = t ?? DEFAULT_TRANSLATE
  if (pointsAccountStatus === 'partial') {
    return {
      label: translate('userCenter.points.statusConnectedLedger'),
      description: translate('userCenter.points.statusConnectedLedgerDesc'),
      color: 'info',
    }
  }

  return {
    label: translate('userCenter.points.statusGradual'),
    description: translate('userCenter.points.statusGradualDesc'),
    color: 'warning',
  }
}

export function buildUserCenterOverviewTabPricingPolicyPresentation(options: {
  pricingPolicy?: UserCenterPointsPricingPolicyOverview | null
  getPricingBasisLabel: (basis?: UserCenterPointsPricingPolicyOverview['user_price_basis'] | null) => string
  formatPercentRate: (value?: number | null) => string
  formatUpdatedAtLabel: (value: string) => string
  /** 可选翻译函数：缺省时原样返回 key（便于测试与纯计算场景）。 */
  t?: TFunction
}): UserCenterOverviewTabPricingPolicyPresentation | null {
  const { pricingPolicy } = options
  const translate = options.t ?? DEFAULT_TRANSLATE

  if (!pricingPolicy) {
    return null
  }

  return {
    sourceColor: pricingPolicy.source === 'admin_log' ? 'primary' : 'default',
    sourceLabel: translate(pricingPolicy.source === 'admin_log' ? 'userCenter.points.sourceAdmin' : 'userCenter.points.sourceDefault'),
    userPriceBasisLabel: translate('userCenter.points.priceBasisTemplate', {
      basis: translate(options.getPricingBasisLabel(pricingPolicy.user_price_basis)),
    }),
    description: translate('userCenter.points.pricingPolicyDescription'),
    summaryItems: [
      { label: translate('userCenter.points.exchangeRate'), value: translate('userCenter.points.exchangeRateValue', { value: pricingPolicy.points_per_yuan }) },
      { label: translate('userCenter.points.pricingBasis'), value: translate(options.getPricingBasisLabel(pricingPolicy.user_price_basis)) },
      { label: translate('userCenter.points.pricingRate'), value: translate('userCenter.points.pricingRateValue', { rate: pricingPolicy.user_price_rate.toFixed(2) }) },
      { label: translate('userCenter.points.freezeBuffer'), value: options.formatPercentRate(pricingPolicy.freeze_buffer_rate) },
    ],
    updatedAtLabel: pricingPolicy.updated_at
      ? translate('userCenter.points.adjustedAt', { time: options.formatUpdatedAtLabel(pricingPolicy.updated_at) })
      : translate('userCenter.points.notAdjustedFull'),
  }
}

export function buildUserCenterOverviewTabMetrics(
  options: BuildUserCenterOverviewTabMetricsOptions,
): UserCenterOverviewTabMetrics {
  return {
    pointsAccountStatusMeta: buildUserCenterOverviewTabPointsAccountStatusMeta(options.pointsAccountStatus, options.t),
    pricingPolicyPresentation: buildUserCenterOverviewTabPricingPolicyPresentation({
      pricingPolicy: options.pricingPolicy,
      getPricingBasisLabel: options.getPricingBasisLabel,
      formatPercentRate: options.formatPercentRate,
      formatUpdatedAtLabel: options.formatUpdatedAtLabel,
      t: options.t,
    }),
  }
}
