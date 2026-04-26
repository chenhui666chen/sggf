type UserCenterAssetRefreshAction = (silent?: boolean) => Promise<void> | void

export type UserCenterAssetRefreshActions = {
  refreshUserCenterData?: UserCenterAssetRefreshAction
  refreshUserAssets: UserCenterAssetRefreshAction
}

export function resolveUserCenterUserAssetCount(
  connectedUserAssetCount?: number | null,
  localUserAssetCount = 0,
): number {
  if (
    typeof connectedUserAssetCount === 'number'
    && Number.isFinite(connectedUserAssetCount)
    && connectedUserAssetCount >= 0
  ) {
    return connectedUserAssetCount
  }
  return Math.max(0, Number(localUserAssetCount) || 0)
}

export function runUserCenterAssetRefresh(
  actions: UserCenterAssetRefreshActions,
): void {
  void actions.refreshUserCenterData?.(true)
  void actions.refreshUserAssets(true)
}
