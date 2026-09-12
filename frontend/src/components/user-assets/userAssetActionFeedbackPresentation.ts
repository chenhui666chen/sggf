import type { TFunction } from 'i18next'

import type { UserAssetBatchActionCommand } from './userAssetListPresentation'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

export function buildUserAssetUpdateSuccessMessage(successText?: string, t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return successText || translate('userAsset.feedback.updateSuccessDefault')
}

export function buildUserAssetUpdateErrorFallback(t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return translate('userAsset.feedback.updateError')
}

export function buildUserAssetBatchSuccessMessage(
  command: Pick<UserAssetBatchActionCommand, 'successText'>,
  updatedCount: number,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return translate('userAsset.feedback.batchSuccess', {
    successText: command.successText,
    count: updatedCount,
  })
}

export function buildUserAssetBatchErrorFallback(
  command: Pick<UserAssetBatchActionCommand, 'label'>,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return translate('userAsset.feedback.batchFailed', { label: command.label })
}

export function buildUserAssetEditorSaveSuccessMessage(t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return translate('userAsset.feedback.saveSuccess')
}

export function buildUserAssetEditorSaveErrorFallback(t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return translate('userAsset.feedback.saveError')
}

export function buildUserAssetLocalCopyClearSuccessMessage(cleared: boolean, t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return cleared ? translate('userAsset.feedback.clearSuccess') : translate('userAsset.feedback.clearNoCopy')
}

export function buildUserAssetLocalCopyClearErrorFallback(t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return translate('userAsset.feedback.clearError')
}

export function buildUserAssetLocalCopyRestoreSuccessMessage(restored: boolean, t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return restored ? translate('userAsset.feedback.restoreSuccess') : translate('userAsset.feedback.restoreAlreadyExists')
}

export function buildUserAssetLocalCopyRestoreErrorFallback(t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return translate('userAsset.feedback.restoreError')
}

type UserAssetLocalCopyBatchSummary = {
  restoredCount: number
  existingCount: number
  blockedCount?: number
  failedCount?: number
}

export function buildUserAssetLocalCopyBatchRestoreSuccessMessage(
  summary: UserAssetLocalCopyBatchSummary,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (summary.restoredCount === 0 && summary.existingCount > 0) {
    return translate('userAsset.feedback.batchRestoreAllExists')
  }

  if (summary.existingCount === 0) {
    return translate('userAsset.feedback.batchRestoreCount', { count: summary.restoredCount })
  }

  return translate('userAsset.feedback.batchRestoreMixed', {
    restored: summary.restoredCount,
    existing: summary.existingCount,
  })
}

export function buildUserAssetLocalCopyBatchRestoreErrorMessage(
  summary: UserAssetLocalCopyBatchSummary,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (
    summary.restoredCount === 0
    && summary.existingCount === 0
    && (summary.blockedCount || 0) > 0
    && (summary.failedCount || 0) === 0
  ) {
    return translate('userAsset.feedback.batchRestoreBlocked', { count: summary.blockedCount || 0 })
  }

  if (summary.restoredCount === 0 && summary.existingCount === 0) {
    return translate('userAsset.feedback.batchRestoreError', { count: summary.failedCount || 0 })
  }

  const blockedText = summary.blockedCount
    ? translate('userAsset.feedback.batchRestoreBlockedSuffix', { count: summary.blockedCount })
    : ''
  return translate('userAsset.feedback.batchRestorePartial', {
    failed: summary.failedCount || 0,
    restored: summary.restoredCount,
    existing: summary.existingCount,
    blocked: blockedText,
  })
}

type UserAssetLocalCopyBatchClearSummary = {
  clearedCount: number
  missingCount: number
  failedCount?: number
}

export function buildUserAssetLocalCopyBatchClearSuccessMessage(
  summary: UserAssetLocalCopyBatchClearSummary,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (summary.clearedCount === 0 && summary.missingCount > 0) {
    return translate('userAsset.feedback.batchClearAllMissing')
  }

  if (summary.missingCount === 0) {
    return translate('userAsset.feedback.batchClearCount', { count: summary.clearedCount })
  }

  return translate('userAsset.feedback.batchClearMixed', {
    cleared: summary.clearedCount,
    missing: summary.missingCount,
  })
}

export function buildUserAssetLocalCopyBatchClearErrorMessage(
  summary: UserAssetLocalCopyBatchClearSummary,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (summary.clearedCount === 0 && summary.missingCount === 0) {
    return translate('userAsset.feedback.batchClearError', { count: summary.failedCount || 0 })
  }

  return translate('userAsset.feedback.batchClearPartial', {
    failed: summary.failedCount || 0,
    cleared: summary.clearedCount,
    missing: summary.missingCount,
  })
}
