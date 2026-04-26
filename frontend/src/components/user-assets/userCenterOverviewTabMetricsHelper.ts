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
}

export function buildUserCenterOverviewTabPointsAccountStatusMeta(
  pointsAccountStatus?: UserCenterPointsAccount['status'] | null,
): UserCenterOverviewTabPointsAccountStatusMeta {
  if (pointsAccountStatus === 'partial') {
    return {
      label: '已接入账本',
      description: '已有真实积分账本与任务计费链路接入用户中心，后续会继续扩展更多消费和权益来源。',
      color: 'info',
    }
  }

  return {
    label: '逐步扩展',
    description: '积分账户结构已就绪，当前已支持积分预检和部分任务计费，更多权益与消费来源会继续接入。',
    color: 'warning',
  }
}

export function buildUserCenterOverviewTabPricingPolicyPresentation(options: {
  pricingPolicy?: UserCenterPointsPricingPolicyOverview | null
  getPricingBasisLabel: (basis?: UserCenterPointsPricingPolicyOverview['user_price_basis'] | null) => string
  formatPercentRate: (value?: number | null) => string
  formatUpdatedAtLabel: (value: string) => string
}): UserCenterOverviewTabPricingPolicyPresentation | null {
  const { pricingPolicy } = options

  if (!pricingPolicy) {
    return null
  }

  return {
    sourceColor: pricingPolicy.source === 'admin_log' ? 'primary' : 'default',
    sourceLabel: pricingPolicy.source === 'admin_log' ? '后台定价快照' : '系统默认定价',
    userPriceBasisLabel: `用户按 ${options.getPricingBasisLabel(pricingPolicy.user_price_basis)} 计点`,
    description: '用户侧按公开价或内部标准价折算积分，不额外加价；运行中任务会按当前缓冲比例预留建议冻结值。',
    summaryItems: [
      { label: '积分汇率', value: `1 元 = ${pricingPolicy.points_per_yuan} 积分` },
      { label: '用户计价基准', value: options.getPricingBasisLabel(pricingPolicy.user_price_basis) },
      { label: '用户计价系数', value: `${pricingPolicy.user_price_rate.toFixed(2)} ×` },
      { label: '冻结缓冲', value: options.formatPercentRate(pricingPolicy.freeze_buffer_rate) },
    ],
    updatedAtLabel: pricingPolicy.updated_at
      ? `最近调整：${options.formatUpdatedAtLabel(pricingPolicy.updated_at)}`
      : '最近调整：尚未人工调整',
  }
}

export function buildUserCenterOverviewTabMetrics(
  options: BuildUserCenterOverviewTabMetricsOptions,
): UserCenterOverviewTabMetrics {
  return {
    pointsAccountStatusMeta: buildUserCenterOverviewTabPointsAccountStatusMeta(options.pointsAccountStatus),
    pricingPolicyPresentation: buildUserCenterOverviewTabPricingPolicyPresentation({
      pricingPolicy: options.pricingPolicy,
      getPricingBasisLabel: options.getPricingBasisLabel,
      formatPercentRate: options.formatPercentRate,
      formatUpdatedAtLabel: options.formatUpdatedAtLabel,
    }),
  }
}
