import type { TFunction } from 'i18next'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

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
  t?: TFunction,
): UserCenterAssetConnectedOverviewItem[] {
  const translate = t ?? DEFAULT_TRANSLATE
  return [
    {
      key: 'connected-project-count',
      label: translate('userAsset.connected.projectCount'),
      value: options.projectCount,
    },
    {
      key: 'connected-user-asset-count',
      label: translate('userAsset.connected.userAssetCount'),
      value: options.userAssetCount,
    },
    {
      key: 'connected-audiobook-project-count',
      label: translate('userAsset.connected.audiobookProjectCount'),
      value: options.audiobookProjectCount,
    },
    {
      key: 'connected-audiobook-total-cost',
      label: translate('userAsset.connected.audiobookTotalCost'),
      value: options.totalAudiobookCostLabel,
    },
    {
      key: 'connected-dreamweaver-run-count',
      label: translate('userAsset.connected.dreamweaverRunCount'),
      value: options.dreamweaverRunCount,
    },
  ]
}

export function buildUserCenterAssetConnectedOverviewSectionProps(
  options: BuildUserCenterAssetConnectedOverviewSectionPropsOptions,
  t?: TFunction,
): UserCenterAssetConnectedOverviewSectionProps {
  return {
    items: buildUserCenterAssetConnectedOverviewItems({
      projectCount: options.connectedProjectCount ?? options.fallbackProjectCount,
      userAssetCount: options.userAssetCount,
      audiobookProjectCount:
        options.connectedAudiobookProjectCount ?? options.fallbackAudiobookProjectCount,
      totalAudiobookCostLabel: options.totalAudiobookCostLabel,
      dreamweaverRunCount: options.dreamweaverRunCount,
    }, t),
  }
}
