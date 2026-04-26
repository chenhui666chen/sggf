import type { UserAssetProjectTitleMap } from '@/contracts/userAssetSourceReaders'
import type { UserCenterPointsOverviewResponse } from '@/services/api'

export type UserCenterAssetWorkspaceProjectInput = {
  id: number
  title?: string | null
}

export type UserCenterAssetWorkspacePointsOverviewInput = Pick<
  UserCenterPointsOverviewResponse,
  'connected_overview'
>

export type UserCenterAssetWorkspaceInput = {
  projectTitleMap: UserAssetProjectTitleMap
  connectedUserAssetCount: number | null
}

export function buildUserCenterAssetProjectTitleMap(
  projects: UserCenterAssetWorkspaceProjectInput[] = [],
): UserAssetProjectTitleMap {
  return new Map(
    projects.map((project) => [project.id, project.title?.trim() || `项目 #${project.id}`] as const),
  )
}

export function extractUserCenterConnectedUserAssetCount(
  pointsOverview?: UserCenterAssetWorkspacePointsOverviewInput | null,
): number | null {
  const connectedUserAssetCount = pointsOverview?.connected_overview?.user_asset_count
  return typeof connectedUserAssetCount === 'number' && Number.isFinite(connectedUserAssetCount)
    ? connectedUserAssetCount
    : null
}

export function buildUserCenterAssetWorkspaceInput(options: {
  projects?: UserCenterAssetWorkspaceProjectInput[]
  pointsOverview?: UserCenterAssetWorkspacePointsOverviewInput | null
}): UserCenterAssetWorkspaceInput {
  return {
    projectTitleMap: buildUserCenterAssetProjectTitleMap(options.projects),
    connectedUserAssetCount: extractUserCenterConnectedUserAssetCount(options.pointsOverview),
  }
}
