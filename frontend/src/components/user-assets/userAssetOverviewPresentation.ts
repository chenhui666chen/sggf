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
): UserAssetOverviewMetricSpec[] {
  return [
    {
      key: 'active-assets',
      title: '活跃资产',
      value: options.activeAssetCount,
      helper: '用户中心负责汇总、筛选和归档，不替代模块内工作台。',
      color: '#2563eb',
    },
    {
      key: 'reusable-assets',
      title: '可复用素材',
      value: `${options.reusableAssetCount} / ${options.deliverableAssetCount}`,
      helper: '优先沉淀可跨项目复用的稳定素材。',
      color: '#7c3aed',
    },
    {
      key: 'favorite-archived-assets',
      title: '重点 / 归档',
      value: `${options.favoriteAssetCount} / ${options.archivedAssetCount}`,
      helper: '重点资产用于快速复用，归档资产用于沉淀历史成果。',
      color: '#f97316',
    },
  ]
}

export function buildUserAssetListFeedbackCopy(): UserAssetListFeedbackCopy {
  return {
    emptyCollectionMessage: '还没有收录到用户中心的资产，后续可以从各生成模块纳入稳定成果。',
    emptyFilterMessage: '当前筛选条件下没有匹配资产，可以切换筛选项查看其他结果。',
  }
}
