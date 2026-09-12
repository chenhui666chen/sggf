import type { TFunction } from 'i18next'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export type UserAssetOverviewMetricSpec = {
  key: string
  title: string
  value: string | number
  helper: string
  color: string
}

export type UserAssetListFeedbackCopy = {
  emptyCollectionMessage: string
  emptyFilterMessage: string
}

type BuildUserAssetOverviewMetricSpecsOptions = {
  activeAssetCount: number
  reusableAssetCount: number
  deliverableAssetCount: number
  favoriteAssetCount: number
  archivedAssetCount: number
}

export function buildUserAssetOverviewMetricSpecs(
  options: BuildUserAssetOverviewMetricSpecsOptions,
  t?: TFunction,
): UserAssetOverviewMetricSpec[] {
  const translate = t ?? DEFAULT_TRANSLATE
  return [
    {
      key: 'active-assets',
      title: translate('userAsset.overview.activeAssets'),
      value: options.activeAssetCount,
      helper: translate('userAsset.overview.activeAssetsHelper'),
      color: '#2563eb', // sg-color-fixed: 指标卡身份色（颜色即数据）
    },
    {
      key: 'reusable-assets',
      title: translate('userAsset.overview.reusableAssets'),
      value: `${options.reusableAssetCount} / ${options.deliverableAssetCount}`,
      helper: translate('userAsset.overview.reusableAssetsHelper'),
      color: '#7c3aed', // sg-color-fixed: 指标卡身份色（颜色即数据）
    },
    {
      key: 'favorite-archived-assets',
      title: translate('userAsset.overview.favoriteArchived'),
      value: `${options.favoriteAssetCount} / ${options.archivedAssetCount}`,
      helper: translate('userAsset.overview.favoriteArchivedHelper'),
      color: '#f97316', // sg-color-fixed: 指标卡身份色（颜色即数据）
    },
  ]
}

export function buildUserAssetListFeedbackCopy(t?: TFunction): UserAssetListFeedbackCopy {
  const translate = t ?? DEFAULT_TRANSLATE
  return {
    emptyCollectionMessage: translate('userAsset.overview.emptyCollection'),
    emptyFilterMessage: translate('userAsset.overview.emptyFilter'),
  }
}
