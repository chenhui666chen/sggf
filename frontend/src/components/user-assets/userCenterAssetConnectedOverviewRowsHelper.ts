import type { ReactElement } from 'react'

import type { BuildUserCenterAssetConnectedOverviewRowsViewModelOptions } from './userCenterAssetConnectedOverviewRowsViewModelHelper'
import {
  buildUserCenterAssetConnectedOverviewRowsViewModel,
} from './userCenterAssetConnectedOverviewRowsViewModelHelper'
import type { TFunction } from 'i18next'

import { buildUserCenterAssetConnectedOverviewRowSlot } from './UserCenterAssetConnectedOverviewRow'

export type UserCenterAssetConnectedOverviewRows = {
  strategyRowSlot: ReactElement
  pointsRulesRowSlot: ReactElement
}

export function buildUserCenterAssetConnectedOverviewRows(
  options: BuildUserCenterAssetConnectedOverviewRowsViewModelOptions,
  t?: TFunction,
): UserCenterAssetConnectedOverviewRows {
  const viewModel = buildUserCenterAssetConnectedOverviewRowsViewModel(options, t)

  return {
    strategyRowSlot: buildUserCenterAssetConnectedOverviewRowSlot(viewModel.strategyRowSlotOptions),
    pointsRulesRowSlot: buildUserCenterAssetConnectedOverviewRowSlot(viewModel.pointsRulesRowSlotOptions),
  }
}
