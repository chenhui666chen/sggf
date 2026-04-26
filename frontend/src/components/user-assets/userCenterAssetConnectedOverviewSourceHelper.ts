import type { UserCenterPointsOverviewResponse } from '@/services/api'

export type UserCenterAssetConnectedOverviewSourcePointsOverviewInput = Pick<
  UserCenterPointsOverviewResponse,
  'connected_overview'
>

export type UserCenterAssetConnectedOverviewSourceOverviewMetricsInput = {
  audiobookProjects: number
}

export type UserCenterAssetConnectedOverviewSource = {
  projectCount: number
  audiobookProjectCount: number
  audiobookTotalCost: number
  dreamweaverRunCount: number
}

export type BuildUserCenterAssetConnectedOverviewSourceOptions = {
  pointsOverview?: UserCenterAssetConnectedOverviewSourcePointsOverviewInput | null
  projectCount: number
  overviewMetrics: UserCenterAssetConnectedOverviewSourceOverviewMetricsInput
}

function normalizeNonNegativeNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
    return value
  }

  const normalizedFallback = Number(fallback)
  if (Number.isFinite(normalizedFallback) && normalizedFallback >= 0) {
    return normalizedFallback
  }

  return 0
}

export function buildUserCenterAssetConnectedOverviewSource(
  options: BuildUserCenterAssetConnectedOverviewSourceOptions,
): UserCenterAssetConnectedOverviewSource {
  const connectedOverview = options.pointsOverview?.connected_overview

  return {
    projectCount: normalizeNonNegativeNumber(
      connectedOverview?.project_count,
      options.projectCount,
    ),
    audiobookProjectCount: normalizeNonNegativeNumber(
      connectedOverview?.audiobook_project_count,
      options.overviewMetrics.audiobookProjects,
    ),
    audiobookTotalCost: normalizeNonNegativeNumber(
      connectedOverview?.audiobook_total_cost,
    ),
    dreamweaverRunCount: normalizeNonNegativeNumber(
      connectedOverview?.dreamweaver_run_count,
    ),
  }
}
