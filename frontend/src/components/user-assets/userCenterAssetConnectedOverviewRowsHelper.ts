import type { ReactElement } from 'react'

import type { BuildUserCenterAssetConnectedOverviewRowsViewModelOptions } from './userCenterAssetConnectedOverviewRowsViewModelHelper'
import {
  buildUserCenterAssetConnectedOverviewRowsViewModel,
} from './userCenterAssetConnectedOverviewRowsViewModelHelper'
import { buildUserCenterAssetConnectedOverviewRowSlot } from './UserCenterAssetConnectedOverviewRow'

export type UserCenterAssetConnectedOverviewRows = {
  strategyRowSlot: ReactElement
  pointsRulesRowSlot: ReactElement
}

export function buildUserCenterAssetConnectedOverviewRows(
  options: BuildUserCenterAssetConnectedOverviewRowsViewModelOptions,
): UserCenterAssetConnectedOverviewRows {
  const viewModel = buildUserCenterAssetConnectedOverviewRowsViewModel(options)

  return {
    strategyRowSlot: buildUserCenterAssetConnectedOverviewRowSlot(viewModel.strategyRowSlotOptions),
    pointsRulesRowSlot: buildUserCenterAssetConnectedOverviewRowSlot(viewModel.pointsRulesRowSlotOptions),
  }
}
