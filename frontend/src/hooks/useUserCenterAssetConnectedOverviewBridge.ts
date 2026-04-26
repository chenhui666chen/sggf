import { useMemo } from 'react'

import type { UserCenterAssetConnectedOverviewSectionProps } from '@/components/user-assets/userCenterAssetConnectedOverviewPresentation'
import {
  buildUserCenterAssetConnectedOverviewViewModel,
  type BuildUserCenterAssetConnectedOverviewViewModelOptions,
  type UserCenterAssetConnectedOverviewViewModel,
} from '@/components/user-assets/userCenterAssetConnectedOverviewViewModelHelper'

export type UserCenterAssetConnectedOverviewBridge = {
  sectionProps: UserCenterAssetConnectedOverviewSectionProps
}

export function buildUserCenterAssetConnectedOverviewBridge(
  viewModel: Pick<UserCenterAssetConnectedOverviewViewModel, 'sectionProps'>,
): UserCenterAssetConnectedOverviewBridge {
  return {
    sectionProps: viewModel.sectionProps,
  }
}

export function useUserCenterAssetConnectedOverviewBridge(
  options: BuildUserCenterAssetConnectedOverviewViewModelOptions,
): UserCenterAssetConnectedOverviewBridge {
  const viewModel = useMemo(
    () => buildUserCenterAssetConnectedOverviewViewModel(options),
    [
      options.userAssetCount,
      options.overviewMetrics.audiobookProjects,
      options.pointsOverview?.connected_overview?.audiobook_project_count,
      options.pointsOverview?.connected_overview?.audiobook_total_cost,
      options.pointsOverview?.connected_overview?.dreamweaver_run_count,
      options.pointsOverview?.connected_overview?.project_count,
      options.projectCount,
      options.formatCurrencyLabel,
    ],
  )

  return useMemo(
    () => buildUserCenterAssetConnectedOverviewBridge(viewModel),
    [viewModel],
  )
}
