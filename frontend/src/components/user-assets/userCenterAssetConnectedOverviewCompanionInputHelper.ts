import type { TFunction } from 'i18next'

import type { UserCenterPointsRuleOverview } from '@/services/api'

import type {
  UserCenterAssetConnectedOverviewPointsRulesCompanionContentOptions,
  UserCenterAssetConnectedOverviewPointsRulesCompanionContentValue,
  UserCenterAssetConnectedOverviewStrategyCompanionContentOptions,
} from './UserCenterAssetConnectedOverviewCompanion'

const STRATEGY_COMPANION_ITEM_KEYS = [
  'userCenter.points.strategyKeepProcess',
  'userCenter.points.strategyCentralizeStable',
  'userCenter.points.strategyDifferentiated',
]

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export type BuildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInputOptions = {
  pointsRules?: UserCenterPointsRuleOverview | null
  formatPointsValueLabel: (value: number) => string
  formatUpdatedAtLabel: (value: string) => string
  getSourceLabel: (source?: UserCenterPointsRuleOverview['source'] | null) => string
  /** 可选翻译函数：缺省时原样返回 key（便于测试与纯计算场景）。 */
  t?: TFunction
}

export function buildUserCenterAssetConnectedOverviewStrategyCompanionContentOptionsFromInput(
  t?: TFunction,
): UserCenterAssetConnectedOverviewStrategyCompanionContentOptions {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    items: STRATEGY_COMPANION_ITEM_KEYS.map((key) => translate(key)),
  }
}

export function buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInput(
  options: BuildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInputOptions,
): UserCenterAssetConnectedOverviewPointsRulesCompanionContentOptions {
  const translate = options.t ?? DEFAULT_TRANSLATE
  return {
    content: buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentValueFromInput(options),
    emptyText: translate('userCenter.points.rulesEmpty'),
  }
}

function buildUserCenterAssetConnectedOverviewPointsRulesCompanionContentValueFromInput(
  options: BuildUserCenterAssetConnectedOverviewPointsRulesCompanionContentOptionsFromInputOptions,
): UserCenterAssetConnectedOverviewPointsRulesCompanionContentValue | null {
  const { pointsRules } = options
  const translate = options.t ?? DEFAULT_TRANSLATE

  if (!pointsRules) {
    return null
  }

  return {
    sourceLabel: translate(options.getSourceLabel(pointsRules.source)),
    sourceColor: pointsRules.source === 'admin_log' ? 'primary' : 'default',
    updatedAtLabel: pointsRules.updated_at
      ? translate('userCenter.points.recentlyUpdated', { time: options.formatUpdatedAtLabel(pointsRules.updated_at) })
      : translate('userCenter.points.notAdjusted'),
    description: translate('userCenter.points.rulesDescription'),
    summaryItems: [
      { label: translate('userCenter.points.reusableReward'), value: translate('userCenter.points.pointsValue', { value: options.formatPointsValueLabel(pointsRules.reusable_asset_reward) }) },
      { label: translate('userCenter.points.deliverableReward'), value: translate('userCenter.points.pointsValue', { value: options.formatPointsValueLabel(pointsRules.deliverable_asset_reward) }) },
      { label: translate('userCenter.points.audiobookCompletionReward'), value: translate('userCenter.points.pointsValue', { value: options.formatPointsValueLabel(pointsRules.audiobook_completion_reward) }) },
      { label: translate('userCenter.points.dreamweaverCompletionReward'), value: translate('userCenter.points.pointsValue', { value: options.formatPointsValueLabel(pointsRules.dreamweaver_completion_reward) }) },
      { label: translate('userCenter.points.runningAudiobookFrozen'), value: translate('userCenter.points.pointsValue', { value: options.formatPointsValueLabel(pointsRules.running_audiobook_frozen) }) },
      { label: translate('userCenter.points.runningDreamweaverFrozen'), value: translate('userCenter.points.pointsValue', { value: options.formatPointsValueLabel(pointsRules.running_dreamweaver_frozen) }) },
      { label: translate('userCenter.points.rewardValidity'), value: translate('userCenter.points.days', { days: pointsRules.reward_ttl_days }) },
      { label: translate('userCenter.points.expiringNoticeWindow'), value: translate('userCenter.points.days', { days: pointsRules.expiring_notice_days }) },
    ],
    updatedByLabel: translate('userCenter.points.updatedBy', { name: pointsRules.updated_by_username || translate('userCenter.points.systemDefault') }),
  }
}
