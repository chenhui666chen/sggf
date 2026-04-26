export type UserCenterAssetConnectedOverviewItem = {
  key: string
  label: string
  value: string | number
}

export type UserCenterAssetConnectedOverviewCardProps = {
  items: UserCenterAssetConnectedOverviewItem[]
}

export type UserCenterAssetConnectedOverviewSectionProps =
  UserCenterAssetConnectedOverviewCardProps

type BuildUserCenterAssetConnectedOverviewItemsOptions = {
  projectCount: number
  userAssetCount: number
  audiobookProjectCount: number
  totalAudiobookCostLabel: string
  dreamweaverRunCount: number
}

type BuildUserCenterAssetConnectedOverviewSectionPropsOptions = {
  connectedProjectCount?: number | null
  fallbackProjectCount: number
  userAssetCount: number
  connectedAudiobookProjectCount?: number | null
  fallbackAudiobookProjectCount: number
  totalAudiobookCostLabel: string
  dreamweaverRunCount: number
}

export function buildUserCenterAssetConnectedOverviewItems(
  options: BuildUserCenterAssetConnectedOverviewItemsOptions,
): UserCenterAssetConnectedOverviewItem[] {
  return [
    {
      key: 'connected-project-count',
      label: '项目数',
      value: options.projectCount,
    },
    {
      key: 'connected-user-asset-count',
      label: '用户资产数',
      value: options.userAssetCount,
    },
    {
      key: 'connected-audiobook-project-count',
      label: '有声书项目数',
      value: options.audiobookProjectCount,
    },
    {
      key: 'connected-audiobook-total-cost',
      label: '有声书累计成本',
      value: options.totalAudiobookCostLabel,
    },
    {
      key: 'connected-dreamweaver-run-count',
      label: '短剧运行次数',
      value: options.dreamweaverRunCount,
    },
  ]
}

export function buildUserCenterAssetConnectedOverviewSectionProps(
  options: BuildUserCenterAssetConnectedOverviewSectionPropsOptions,
): UserCenterAssetConnectedOverviewSectionProps {
  return {
    items: buildUserCenterAssetConnectedOverviewItems({
      projectCount: options.connectedProjectCount ?? options.fallbackProjectCount,
      userAssetCount: options.userAssetCount,
      audiobookProjectCount:
        options.connectedAudiobookProjectCount ?? options.fallbackAudiobookProjectCount,
      totalAudiobookCostLabel: options.totalAudiobookCostLabel,
      dreamweaverRunCount: options.dreamweaverRunCount,
    }),
  }
}
