import {
  buildUserCenterAssetConnectedOverviewSectionProps,
  type UserCenterAssetConnectedOverviewSectionProps,
} from './userCenterAssetConnectedOverviewPresentation'
import type { TFunction } from 'i18next'

import type { UserCenterAssetConnectedOverviewSource } from './userCenterAssetConnectedOverviewSourceHelper'

export type BuildUserCenterAssetConnectedOverviewSectionPropsFromInputOptions = {
  connectedOverviewSource: UserCenterAssetConnectedOverviewSource
  userAssetCount: number
  totalAudiobookCostLabel: string
  t?: TFunction
}

export function buildUserCenterAssetConnectedOverviewSectionPropsFromInput(
  options: BuildUserCenterAssetConnectedOverviewSectionPropsFromInputOptions,
): UserCenterAssetConnectedOverviewSectionProps {
  return buildUserCenterAssetConnectedOverviewSectionProps({
    connectedProjectCount: options.connectedOverviewSource.projectCount,
    fallbackProjectCount: options.connectedOverviewSource.projectCount,
    userAssetCount: options.userAssetCount,
    connectedAudiobookProjectCount: options.connectedOverviewSource.audiobookProjectCount,
    fallbackAudiobookProjectCount: options.connectedOverviewSource.audiobookProjectCount,
    totalAudiobookCostLabel: options.totalAudiobookCostLabel,
    dreamweaverRunCount: options.connectedOverviewSource.dreamweaverRunCount,
  }, options.t)
}
