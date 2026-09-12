import type { TFunction } from 'i18next'

import type { UserCenterAssetConnectedOverviewCompanionViewModel } from './userCenterAssetConnectedOverviewCompanionViewModelHelper'
import {
  buildUserCenterAssetConnectedOverviewPointsRulesCompanionContent,
  buildUserCenterAssetConnectedOverviewStrategyCompanionContent,
} from './UserCenterAssetConnectedOverviewCompanion'
import type { UserCenterAssetConnectedOverviewRowSlotOptions } from './UserCenterAssetConnectedOverviewRow'
import type { UserCenterAssetConnectedOverviewSectionSlotBridge } from './UserCenterAssetConnectedOverviewSectionBridge'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export type UserCenterAssetConnectedOverviewRowsViewModel = {
  strategyRowSlotOptions: UserCenterAssetConnectedOverviewRowSlotOptions
  pointsRulesRowSlotOptions: UserCenterAssetConnectedOverviewRowSlotOptions
}

export type BuildUserCenterAssetConnectedOverviewRowsViewModelOptions = {
  overviewBridge: UserCenterAssetConnectedOverviewSectionSlotBridge
  companionViewModel: UserCenterAssetConnectedOverviewCompanionViewModel
}

export function buildUserCenterAssetConnectedOverviewRowsViewModel(
  options: BuildUserCenterAssetConnectedOverviewRowsViewModelOptions,
  t?: TFunction,
): UserCenterAssetConnectedOverviewRowsViewModel {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    strategyRowSlotOptions: {
      overviewBridge: options.overviewBridge,
      companionTitle: translate('userCenter.points.strategyCompanionTitle'),
      companionContent: buildUserCenterAssetConnectedOverviewStrategyCompanionContent(
        options.companionViewModel.strategyCompanionContentOptions,
      ),
    },
    pointsRulesRowSlotOptions: {
      overviewBridge: options.overviewBridge,
      companionTitle: translate('userCenter.points.rulesCompanionTitle'),
      companionContent: buildUserCenterAssetConnectedOverviewPointsRulesCompanionContent(
        options.companionViewModel.pointsRulesCompanionContentOptions,
      ),
    },
  }
}
