import { useMemo } from 'react'

import {
  buildUserCenterAssetConnectedOverviewCompanionViewModel,
} from '@/components/user-assets/userCenterAssetConnectedOverviewCompanionViewModelHelper'
import type {
  UserCenterAssetConnectedOverviewRowsOptions,
} from '@/components/user-assets/userCenterAssetConnectedOverviewRowsInputHelper'
import {
  buildUserCenterAssetConnectedOverviewRows,
  type UserCenterAssetConnectedOverviewRows,
} from '@/components/user-assets/userCenterAssetConnectedOverviewRowsHelper'
import {
  useUserCenterAssetConnectedOverviewBridge,
} from '@/hooks/useUserCenterAssetConnectedOverviewBridge'

export type UserCenterAssetConnectedOverviewRowsFacade = UserCenterAssetConnectedOverviewRows

export type UseUserCenterAssetConnectedOverviewRowsOptions = UserCenterAssetConnectedOverviewRowsOptions

export function buildUserCenterAssetConnectedOverviewRowsFacade(
  rows: UserCenterAssetConnectedOverviewRows,
): UserCenterAssetConnectedOverviewRowsFacade {
  return rows
}

export function useUserCenterAssetConnectedOverviewRows(
  options: UseUserCenterAssetConnectedOverviewRowsOptions,
): UserCenterAssetConnectedOverviewRowsFacade {
  const overviewBridge = useUserCenterAssetConnectedOverviewBridge(options)
  const companionViewModel = useMemo(
    () => buildUserCenterAssetConnectedOverviewCompanionViewModel({
      pointsRules: options.pointsOverview?.points_rules ?? null,
      formatPointsValueLabel: options.formatPointsValueLabel,
      formatUpdatedAtLabel: options.formatUpdatedAtLabel,
      getSourceLabel: options.getSourceLabel,
    }),
    [
      options.pointsOverview?.points_rules,
      options.formatPointsValueLabel,
      options.formatUpdatedAtLabel,
      options.getSourceLabel,
    ],
  )

  const rows = useMemo(
    () => buildUserCenterAssetConnectedOverviewRows({
      overviewBridge,
      companionViewModel,
    }),
    [companionViewModel, overviewBridge],
  )

  return useMemo(
    () => buildUserCenterAssetConnectedOverviewRowsFacade(rows),
    [rows],
  )
}
