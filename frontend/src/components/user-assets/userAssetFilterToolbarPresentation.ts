import type { TFunction } from 'i18next'

import type {
  UserAssetListArchiveFilter,
  UserAssetListFilters,
  UserAssetListViewFilter,
  UserAssetSourceOption,
} from './userAssetListPresentation'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export type UserAssetFilterToolbarFieldKey =
  | 'viewFilter'
  | 'kindFilter'
  | 'sourceFilter'
  | 'archiveFilter'
  | 'tagFilter'

export type UserAssetFilterToolbarOption = {
  value: string
  label: string
}

export type UserAssetFilterToolbarField = {
  key: UserAssetFilterToolbarFieldKey
  label: string
  value: string
  options: UserAssetFilterToolbarOption[]
}

export type UserAssetFilterToolbarPresentation = {
  fields: UserAssetFilterToolbarField[]
  resultLabel: string
  refreshLabel: string
  refreshDisabled: boolean
}

type BuildUserAssetFilterToolbarPresentationOptions = {
  filters: Pick<
    UserAssetListFilters,
    'viewFilter' | 'kindFilter' | 'sourceFilter' | 'archiveFilter' | 'tagFilter'
  >
  kindOptions: string[]
  sourceOptions: UserAssetSourceOption[]
  tagOptions: string[]
  filteredCount: number
  loading?: boolean
}

function buildViewFilterOptions(t?: TFunction): UserAssetFilterToolbarOption[] {
  const translate = t ?? DEFAULT_TRANSLATE
  return [
    { value: 'all', label: translate('userAsset.filter.allAssets') },
    { value: 'favorites', label: translate('userAsset.filter.favoritesOnly') },
    { value: 'deliverable', label: translate('userAsset.filter.deliverableOnly') },
    { value: 'reusable', label: translate('userAsset.filter.reusableOnly') },
  ]
}

function buildArchiveFilterOptions(t?: TFunction): UserAssetFilterToolbarOption[] {
  const translate = t ?? DEFAULT_TRANSLATE
  return [
    { value: 'active', label: translate('userAsset.filter.activeAssets') },
    { value: 'archived', label: translate('userAsset.filter.archivedAssets') },
    { value: 'all', label: translate('userAsset.filter.all') },
  ]
}

function buildValueOptions(
  allLabel: string,
  values: string[],
): UserAssetFilterToolbarOption[] {
  return [
    { value: 'all', label: allLabel },
    ...values.map((value) => ({ value, label: value })),
  ]
}

function buildSourceFilterOptions(
  sourceOptions: UserAssetSourceOption[],
  t?: TFunction,
): UserAssetFilterToolbarOption[] {
  const translate = t ?? DEFAULT_TRANSLATE
  return [
    { value: 'all', label: translate('userAsset.filter.allSources') },
    ...sourceOptions.map((option) => ({
      value: option.value,
      label: option.label,
    })),
  ]
}

export function buildUserAssetFilterToolbarPresentation(
  options: BuildUserAssetFilterToolbarPresentationOptions,
  t?: TFunction,
): UserAssetFilterToolbarPresentation {
  const translate = t ?? DEFAULT_TRANSLATE
  const {
    filters,
    kindOptions,
    sourceOptions,
    tagOptions,
    filteredCount,
    loading = false,
  } = options

  return {
    fields: [
      {
        key: 'viewFilter',
        label: translate('userAsset.filter.viewLabel'),
        value: filters.viewFilter,
        options: buildViewFilterOptions(t),
      },
      {
        key: 'kindFilter',
        label: translate('userAsset.filter.kindLabel'),
        value: filters.kindFilter,
        options: buildValueOptions(translate('userAsset.filter.allKinds'), kindOptions),
      },
      {
        key: 'sourceFilter',
        label: translate('userAsset.filter.sourceLabel'),
        value: filters.sourceFilter,
        options: buildSourceFilterOptions(sourceOptions, t),
      },
      {
        key: 'archiveFilter',
        label: translate('userAsset.filter.archiveLabel'),
        value: filters.archiveFilter,
        options: buildArchiveFilterOptions(t),
      },
      {
        key: 'tagFilter',
        label: translate('userAsset.filter.tagLabel'),
        value: filters.tagFilter,
        options: buildValueOptions(translate('userAsset.filter.allTags'), tagOptions),
      },
    ],
    resultLabel: translate('userAsset.filter.resultCount', { count: filteredCount }),
    refreshLabel: translate('userAsset.filter.refresh'),
    refreshDisabled: loading,
  }
}

export function isUserAssetViewFilter(
  value: string,
): value is UserAssetListViewFilter {
  return ['all', 'favorites', 'deliverable', 'reusable'].includes(value)
}

export function isUserAssetArchiveFilter(
  value: string,
): value is UserAssetListArchiveFilter {
  return ['active', 'archived', 'all'].includes(value)
}
