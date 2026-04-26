import type { UserAssetBatchActionCommand } from './userAssetListPresentation'

export function buildUserAssetUpdateSuccessMessage(successText = '资产信息已更新'): string {
  return successText
}

export function buildUserAssetUpdateErrorFallback(): string {
  return '更新用户资产失败'
}

export function buildUserAssetBatchSuccessMessage(
  command: Pick<UserAssetBatchActionCommand, 'successText'>,
  updatedCount: number,
): string {
  return `${command.successText}，共处理 ${updatedCount} 项资产`
}

export function buildUserAssetBatchErrorFallback(
  command: Pick<UserAssetBatchActionCommand, 'label'>,
): string {
  return `${command.label}失败`
}

export function buildUserAssetEditorSaveSuccessMessage(): string {
  return '资产内容已保存'
}

export function buildUserAssetEditorSaveErrorFallback(): string {
  return '保存资产失败'
}

export function buildUserAssetLocalCopyClearSuccessMessage(cleared: boolean): string {
  return cleared ? '已清理当前浏览器中的本地副本' : '当前浏览器未发现本地副本'
}

export function buildUserAssetLocalCopyClearErrorFallback(): string {
  return '清理本地副本失败'
}

export function buildUserAssetLocalCopyRestoreSuccessMessage(restored: boolean): string {
  return restored ? '已重新收录到本地' : '当前浏览器已存在本地副本'
}

export function buildUserAssetLocalCopyRestoreErrorFallback(): string {
  return '重新收录到本地失败'
}

type UserAssetLocalCopyBatchSummary = {
  restoredCount: number
  existingCount: number
  blockedCount?: number
  failedCount?: number
}

export function buildUserAssetLocalCopyBatchRestoreSuccessMessage(
  summary: UserAssetLocalCopyBatchSummary,
): string {
  if (summary.restoredCount === 0 && summary.existingCount > 0) {
    return '所选资产当前浏览器中已存在本地副本'
  }

  if (summary.existingCount === 0) {
    return `已重新收录 ${summary.restoredCount} 项本地副本`
  }

  return `已重新收录 ${summary.restoredCount} 项本地副本，${summary.existingCount} 项当前浏览器已存在本地副本`
}

export function buildUserAssetLocalCopyBatchRestoreErrorMessage(
  summary: UserAssetLocalCopyBatchSummary,
): string {
  if (
    summary.restoredCount === 0
    && summary.existingCount === 0
    && (summary.blockedCount || 0) > 0
    && (summary.failedCount || 0) === 0
  ) {
    return `所选资产当前无法恢复到登记的本地存储，共 ${summary.blockedCount || 0} 项受阻`
  }

  if (summary.restoredCount === 0 && summary.existingCount === 0) {
    return `批量重新收录到本地失败，共 ${summary.failedCount || 0} 项失败`
  }

  const blockedText = summary.blockedCount ? `，${summary.blockedCount} 项因目标存储不可用未恢复` : ''
  return `批量重新收录到本地时有 ${summary.failedCount || 0} 项失败；已重新收录 ${summary.restoredCount} 项，${summary.existingCount} 项已存在本地副本${blockedText}`
}

type UserAssetLocalCopyBatchClearSummary = {
  clearedCount: number
  missingCount: number
  failedCount?: number
}

export function buildUserAssetLocalCopyBatchClearSuccessMessage(
  summary: UserAssetLocalCopyBatchClearSummary,
): string {
  if (summary.clearedCount === 0 && summary.missingCount > 0) {
    return '当前浏览器未发现所选资产的本地副本'
  }

  if (summary.missingCount === 0) {
    return `已清理 ${summary.clearedCount} 项本地副本`
  }

  return `已清理 ${summary.clearedCount} 项本地副本，${summary.missingCount} 项当前浏览器未发现本地副本`
}

export function buildUserAssetLocalCopyBatchClearErrorMessage(
  summary: UserAssetLocalCopyBatchClearSummary,
): string {
  if (summary.clearedCount === 0 && summary.missingCount === 0) {
    return `批量清理本地副本失败，共 ${summary.failedCount || 0} 项失败`
  }

  return `批量清理本地副本时有 ${summary.failedCount || 0} 项失败；已清理 ${summary.clearedCount} 项，${summary.missingCount} 项未发现本地副本`
}
