import type { UserAssetWorkspaceContentProps } from './UserAssetWorkspaceContent'

export type UserCenterAssetFacade = {
  userAssetCount: number
  refreshUserCenterAssets: () => void
  workspaceContentProps: UserAssetWorkspaceContentProps
}

export function buildUserCenterAssetFacade(
  options: UserCenterAssetFacade,
): UserCenterAssetFacade {
  return {
    userAssetCount: options.userAssetCount,
    refreshUserCenterAssets: options.refreshUserCenterAssets,
    workspaceContentProps: options.workspaceContentProps,
  }
}
