import { useMemo } from 'react'

import {
  buildUserCenterAssetConnectedOverviewRowsOptionsFromInput,
  type BuildUserCenterAssetConnectedOverviewRowsOptionsFromInputOptions,
} from '@/components/user-assets/userCenterAssetConnectedOverviewRowsInputHelper'

import {
  useUserCenterAssetConnectedOverviewRows,
  type UserCenterAssetConnectedOverviewRowsFacade,
} from './useUserCenterAssetConnectedOverviewRows'

export type UseUserCenterAssetConnectedOverviewRowsFromInputOptions =
  BuildUserCenterAssetConnectedOverviewRowsOptionsFromInputOptions
export type UserCenterAssetConnectedOverviewRowsFromInputFacade =
  UserCenterAssetConnectedOverviewRowsFacade

export function useUserCenterAssetConnectedOverviewRowsFromInput(
  options: UseUserCenterAssetConnectedOverviewRowsFromInputOptions,
): UserCenterAssetConnectedOverviewRowsFromInputFacade {
  const rowsOptions = useMemo(
    () => buildUserCenterAssetConnectedOverviewRowsOptionsFromInput(options),
    [
      options.pointsOverview?.connected_overview,
      options.pointsOverview?.points_rules,
      options.projects?.length,
      options.userAssetCount,
      options.overviewMetrics.audiobookProjects,
      options.formatCurrencyLabel,
      options.formatPointsValueLabel,
      options.formatUpdatedAtLabel,
      options.getSourceLabel,
    ],
  )

  return useUserCenterAssetConnectedOverviewRows(rowsOptions)
}
