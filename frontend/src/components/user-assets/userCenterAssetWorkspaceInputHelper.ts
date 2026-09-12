import type { TFunction } from 'i18next'
import type { UserAssetProjectTitleMap } from '@/contracts/userAssetSourceReaders'
import type { UserCenterPointsOverviewResponse } from '@/services/api'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

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
  t?: TFunction,
): UserAssetProjectTitleMap {
  const translate = t ?? DEFAULT_TRANSLATE
  return new Map(
    projects.map((project) => [project.id, project.title?.trim() || translate('userAsset.projectFallback', { id: project.id })] as const),
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
  t?: TFunction
}): UserCenterAssetWorkspaceInput {
  return {
    projectTitleMap: buildUserCenterAssetProjectTitleMap(options.projects, options.t),
    connectedUserAssetCount: extractUserCenterConnectedUserAssetCount(options.pointsOverview),
  }
}
