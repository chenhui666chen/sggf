import type { UserCenterAssetConnectedOverviewCompanionViewModel } from './userCenterAssetConnectedOverviewCompanionViewModelHelper'
import {
  buildUserCenterAssetConnectedOverviewPointsRulesCompanionContent,
  buildUserCenterAssetConnectedOverviewStrategyCompanionContent,
} from './UserCenterAssetConnectedOverviewCompanion'
import type { UserCenterAssetConnectedOverviewRowSlotOptions } from './UserCenterAssetConnectedOverviewRow'
import type { UserCenterAssetConnectedOverviewSectionSlotBridge } from './UserCenterAssetConnectedOverviewSectionBridge'

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
): UserCenterAssetConnectedOverviewRowsViewModel {
  return {
    strategyRowSlotOptions: {
      overviewBridge: options.overviewBridge,
      companionTitle: '资产接入策略',
      companionContent: buildUserCenterAssetConnectedOverviewStrategyCompanionContent(
        options.companionViewModel.strategyCompanionContentOptions,
      ),
    },
    pointsRulesRowSlotOptions: {
      overviewBridge: options.overviewBridge,
      companionTitle: '当前积分规则',
      companionContent: buildUserCenterAssetConnectedOverviewPointsRulesCompanionContent(
        options.companionViewModel.pointsRulesCompanionContentOptions,
      ),
    },
  }
}
