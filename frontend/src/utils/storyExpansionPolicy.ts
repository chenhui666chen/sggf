export const CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS = 450
export const CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS = 600
export const FRAMEWORK_PREFERRED_TOTAL_FROM = 451
export const EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS = 300
export const EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS = 5000
export const EPIC_RECOMMENDATION_CHAPTER_THRESHOLD = 700
export const VOLUME_DETAIL_MIN_CHAPTERS = 20
export const VOLUME_DETAIL_MAX_CHAPTERS = 120
export const ITERATIVE_CHAPTER_STEP = 60

export function buildConventionalCollaborationLimitMessage(): string {
  return (
    `常规协同仅支持总规模不超过${CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS}个细化章节；`
    + `${FRAMEWORK_PREFERRED_TOTAL_FROM}章起建议优先改用长篇框架协同，`
    + `超过${CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS}章后必须切换。`
  )
}

export function buildConventionalCollaborationRecommendationMessage(): string {
  return (
    `常规协同推荐总规模不超过${CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS}个细化章节；`
    + `${FRAMEWORK_PREFERRED_TOTAL_FROM}-${CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS}章仍可执行，`
    + '但更建议先切换到长篇框架协同。'
  )
}

export function buildEpicFrameworkTotalRangeText(): string {
  return `${EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS}-${EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS}`
}

export function buildVolumeDetailChapterRangeText(): string {
  return `${VOLUME_DETAIL_MIN_CHAPTERS}-${VOLUME_DETAIL_MAX_CHAPTERS}`
}
