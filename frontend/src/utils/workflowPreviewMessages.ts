import type { StageType } from '@/store/slices/workflowSlice'
import type { TFunction } from 'i18next'

export function getWorkflowPreviewLoadingLabel(
  stage: StageType,
  isGeneratingNextChapter: boolean,
  t?: TFunction,
): string {
  if (isGeneratingNextChapter && stage === 'iteration') {
    return t ? t('workflow.previewMessages.iterating') : '迭代优化中...'
  }

  return t ? t('workflow.previewMessages.generating') : '正在生成...'
}

export function getWorkflowPreviewEmptyMessage(
  stage: StageType,
  progressMessage: string,
  isGeneratingNextChapter: boolean,
  t?: TFunction,
): string {
  if (progressMessage) {
    return progressMessage
  }

  if (isGeneratingNextChapter && stage === 'iteration') {
    return t ? t('workflow.previewMessages.rewriting') : '正在内部改稿和复评，最终版本确认后会展示正文，请等待...'
  }

  return t ? t('workflow.previewMessages.waiting') : '等待内容生成...'
}
