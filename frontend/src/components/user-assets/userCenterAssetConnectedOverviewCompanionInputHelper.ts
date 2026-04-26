import type { UserCenterPointsRuleOverview } from '@/services/api'

import type {
  UserCenterAssetConnectedOverviewPointsRulesCompanionContentOptions,
  UserCenterAssetConnectedOverviewPointsRulesCompanionContentValue,
  UserCenterAssetConnectedOverviewStrategyCompanionContentOptions,
} from './UserCenterAssetConnectedOverviewCompanion'

const STRATEGY_COMPANION_ITEMS = [
  '过程态资产继续保留在生成模块，避免用户中心承接复杂上下文操作。',
  '稳定素材、成片和跨模块复用结果进入用户中心，便于统一检索、标记和权益联动。',
  '不同类型资产采取不同策略，生成链路负责生产，用户中心负责汇总与治理。',
]

const POINTS_RULES_DESCRIPTION = '这里展示当前积分模型实际采用的奖励、冻结和过期规则。'
const POINTS_RULES_EMPTY_TEXT = '暂无可展示的积分规则快照。'

export type BuildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInputOptions = {
  pointsRules?: UserCenterPointsRuleOverview | null
  formatPointsValueLabel: (value: number) => string
  formatUpdatedAtLabel: (value: string) => string
  getSourceLabel: (source?: UserCenterPointsRuleOverview['source'] | null) => string
}

export function buildUserCenterAssetConnectedOverviewStrategyCompanionContentOptionsFromInput():
UserCenterAssetConnectedOverviewStrategyCompanionContentOptions {
  return {
    items: STRATEGY_COMPANION_ITEMS,
  }
}

export function buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput(
  options: BuildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInputOptions,
): UserCenterAssetConnectedOverviewPointsRulesCompanionContentOptions {
  return {
    content: buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentValueFromInput(options),
    emptyText: POINTS_RULES_EMPTY_TEXT,
  }
}

function buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentValueFromInput(
  options: BuildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInputOptions,
): UserCenterAssetConnectedOverviewPointsRulesCompanionContentValue | null {
  const { pointsRules } = options

  if (!pointsRules) {
    return null
  }

  return {
    sourceLabel: options.getSourceLabel(pointsRules.source),
    sourceColor: pointsRules.source === 'admin_log' ? 'primary' : 'default',
    updatedAtLabel: pointsRules.updated_at
      ? `最近更新：${options.formatUpdatedAtLabel(pointsRules.updated_at)}`
      : '尚未人工调整',
    description: POINTS_RULES_DESCRIPTION,
    summaryItems: [
      { label: '复用资产奖励', value: `${options.formatPointsValueLabel(pointsRules.reusable_asset_reward)} 积分` },
      { label: '交付资产奖励', value: `${options.formatPointsValueLabel(pointsRules.deliverable_asset_reward)} 积分` },
      { label: '有声书完成奖励', value: `${options.formatPointsValueLabel(pointsRules.audiobook_completion_reward)} 积分` },
      { label: '短剧完成奖励', value: `${options.formatPointsValueLabel(pointsRules.dreamweaver_completion_reward)} 积分` },
      { label: '有声书运行冻结', value: `${options.formatPointsValueLabel(pointsRules.running_audiobook_frozen)} 积分` },
      { label: '短剧运行冻结', value: `${options.formatPointsValueLabel(pointsRules.running_dreamweaver_frozen)} 积分` },
      { label: '奖励有效期', value: `${pointsRules.reward_ttl_days} 天` },
      { label: '到期提醒窗口', value: `${pointsRules.expiring_notice_days} 天` },
    ],
    updatedByLabel: `最近操作人：${pointsRules.updated_by_username || '系统默认'}`,
  }
}
