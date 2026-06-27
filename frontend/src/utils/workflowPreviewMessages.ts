import type { StageType } from '@/store/slices/workflowSlice'

export function getWorkflowPreviewLoadingLabel(
  stage: StageType,
  isGeneratingNextChapter: boolean,
): string {
  if (isGeneratingNextChapter && stage === 'iteration') {
    return '迭代优化中...'
  }

  return '正在生成...'
}

export function getWorkflowPreviewEmptyMessage(
  stage: StageType,
  progressMessage: string,
  isGeneratingNextChapter: boolean,
): string {
  if (progressMessage) {
    return progressMessage
  }

  if (isGeneratingNextChapter && stage === 'iteration') {
    return '正在内部改稿和复评，最终版本确认后会展示正文，请等待...'
  }

  return '等待内容生成...'
}
