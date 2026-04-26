import type {
  UserAssetListArchiveFilter,
  UserAssetListFilters,
  UserAssetListViewFilter,
  UserAssetSourceOption,
} from './userAssetListPresentation'

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

function buildViewFilterOptions(): UserAssetFilterToolbarOption[] {
  return [
    { value: 'all', label: '全部资产' },
    { value: 'favorites', label: '仅看重点' },
    { value: 'deliverable', label: '仅看成品' },
    { value: 'reusable', label: '仅看可复用' },
  ]
}

function buildArchiveFilterOptions(): UserAssetFilterToolbarOption[] {
  return [
    { value: 'active', label: '活跃资产' },
    { value: 'archived', label: '已归档' },
    { value: 'all', label: '全部' },
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
): UserAssetFilterToolbarOption[] {
  return [
    { value: 'all', label: '全部来源' },
    ...sourceOptions.map((option) => ({
      value: option.value,
      label: option.label,
    })),
  ]
}

export function buildUserAssetFilterToolbarPresentation(
  options: BuildUserAssetFilterToolbarPresentationOptions,
): UserAssetFilterToolbarPresentation {
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
        label: '资产视角',
        value: filters.viewFilter,
        options: buildViewFilterOptions(),
      },
      {
        key: 'kindFilter',
        label: '资产类型',
        value: filters.kindFilter,
        options: buildValueOptions('全部类型', kindOptions),
      },
      {
        key: 'sourceFilter',
        label: '来源模块',
        value: filters.sourceFilter,
        options: buildSourceFilterOptions(sourceOptions),
      },
      {
        key: 'archiveFilter',
        label: '归档范围',
        value: filters.archiveFilter,
        options: buildArchiveFilterOptions(),
      },
      {
        key: 'tagFilter',
        label: '标签',
        value: filters.tagFilter,
        options: buildValueOptions('全部标签', tagOptions),
      },
    ],
    resultLabel: `当前结果 ${filteredCount}`,
    refreshLabel: '刷新资产',
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
