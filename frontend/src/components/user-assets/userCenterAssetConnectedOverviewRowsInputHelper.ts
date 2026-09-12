import type {
  BuildUserCenterAssetConnectedOverviewCompanionViewModelOptions,
} from './userCenterAssetConnectedOverviewCompanionViewModelHelper'
import type {
  BuildUserCenterAssetConnectedOverviewViewModelOptions,
} from './userCenterAssetConnectedOverviewViewModelHelper'
import type { UserCenterPointsOverviewResponse } from '@/services/api'

export type UserCenterAssetConnectedOverviewRowsPointsOverviewInput = Pick<
  UserCenterPointsOverviewResponse,
  'connected_overview' | 'points_rules'
>

export type UserCenterAssetConnectedOverviewRowsOptions =
  Omit<BuildUserCenterAssetConnectedOverviewViewModelOptions, 'pointsOverview'>
  & Omit<BuildUserCenterAssetConnectedOverviewCompanionViewModelOptions, 'pointsRules'>
  & {
    pointsOverview?: UserCenterAssetConnectedOverviewRowsPointsOverviewInput | null
  }

export type BuildUserCenterAssetConnectedOverviewRowsOptionsFromInputOptions =
  Omit<UserCenterAssetConnectedOverviewRowsOptions, 'projectCount'>
  & {
    projects?: readonly unknown[] | null
  }

export function buildUserCenterAssetConnectedOverviewRowsOptionsFromInput(
  options: BuildUserCenterAssetConnectedOverviewRowsOptionsFromInputOptions,
): UserCenterAssetConnectedOverviewRowsOptions {
  return {
    pointsOverview: options.pointsOverview,
    projectCount: options.projects?.length ?? 0,
    userAssetCount: options.userAssetCount,
    overviewMetrics: options.overviewMetrics,
    formatCurrencyLabel: options.formatCurrencyLabel,
    formatPointsValueLabel: options.formatPointsValueLabel,
    formatUpdatedAtLabel: options.formatUpdatedAtLabel,
    getSourceLabel: options.getSourceLabel,
    t: options.t,
  }
}
