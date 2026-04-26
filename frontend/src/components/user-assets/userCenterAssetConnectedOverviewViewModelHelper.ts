import {
  buildUserCenterAssetConnectedOverviewSectionPropsFromInput,
  type BuildUserCenterAssetConnectedOverviewSectionPropsFromInputOptions,
} from './userCenterAssetConnectedOverviewInputHelper'
import {
  buildUserCenterAssetConnectedOverviewSource,
  type BuildUserCenterAssetConnectedOverviewSourceOptions,
  type UserCenterAssetConnectedOverviewSource,
} from './userCenterAssetConnectedOverviewSourceHelper'
import type { UserCenterAssetConnectedOverviewSectionProps } from './userCenterAssetConnectedOverviewPresentation'

export type UserCenterAssetConnectedOverviewViewModel = {
  source: UserCenterAssetConnectedOverviewSource
  sectionProps: UserCenterAssetConnectedOverviewSectionProps
}

export type BuildUserCenterAssetConnectedOverviewViewModelOptions =
  BuildUserCenterAssetConnectedOverviewSourceOptions
  & Pick<BuildUserCenterAssetConnectedOverviewSectionPropsFromInputOptions, 'userAssetCount'>
  & {
    formatCurrencyLabel: (value: number) => string
  }

export function buildUserCenterAssetConnectedOverviewViewModel(
  options: BuildUserCenterAssetConnectedOverviewViewModelOptions,
): UserCenterAssetConnectedOverviewViewModel {
  const source = buildUserCenterAssetConnectedOverviewSource(options)

  return {
    source,
    sectionProps: buildUserCenterAssetConnectedOverviewSectionPropsFromInput({
      connectedOverviewSource: source,
      userAssetCount: options.userAssetCount,
      totalAudiobookCostLabel: options.formatCurrencyLabel(source.audiobookTotalCost),
    }),
  }
}
