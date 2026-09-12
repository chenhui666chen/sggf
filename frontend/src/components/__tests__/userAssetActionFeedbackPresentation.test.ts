import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import {
  buildUserAssetBatchErrorFallback,
  buildUserAssetBatchSuccessMessage,
  buildUserAssetEditorSaveErrorFallback,
  buildUserAssetEditorSaveSuccessMessage,
  buildUserAssetLocalCopyBatchClearErrorMessage,
  buildUserAssetLocalCopyBatchClearSuccessMessage,
  buildUserAssetLocalCopyBatchRestoreErrorMessage,
  buildUserAssetLocalCopyBatchRestoreSuccessMessage,
  buildUserAssetLocalCopyClearErrorFallback,
  buildUserAssetLocalCopyClearSuccessMessage,
  buildUserAssetLocalCopyRestoreErrorFallback,
  buildUserAssetLocalCopyRestoreSuccessMessage,
  buildUserAssetUpdateErrorFallback,
  buildUserAssetUpdateSuccessMessage,
} from '../user-assets/userAssetActionFeedbackPresentation'

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userAssetActionFeedbackPresentation', () => {
  it('builds single asset update feedback messages', () => {
    expect(buildUserAssetUpdateSuccessMessage(undefined, t)).toBe('资产信息已更新')
    expect(buildUserAssetUpdateSuccessMessage('已设为重点资产')).toBe('已设为重点资产')
    expect(buildUserAssetUpdateErrorFallback(t)).toBe('更新用户资产失败')
  })

  it('builds batch, editor and local copy feedback messages', () => {
    expect(
      buildUserAssetBatchSuccessMessage({ successText: '已批量归档' }, 3, t),
    ).toBe('已批量归档，共处理 3 项资产')
    expect(buildUserAssetBatchErrorFallback({ label: '归档' }, t)).toBe('归档失败')
    expect(buildUserAssetEditorSaveSuccessMessage(t)).toBe('资产内容已保存')
    expect(buildUserAssetEditorSaveErrorFallback(t)).toBe('保存资产失败')
    expect(buildUserAssetLocalCopyClearSuccessMessage(true, t)).toBe('已清理当前浏览器中的本地副本')
    expect(buildUserAssetLocalCopyClearSuccessMessage(false, t)).toBe('当前浏览器未发现本地副本')
    expect(buildUserAssetLocalCopyClearErrorFallback(t)).toBe('清理本地副本失败')
    expect(buildUserAssetLocalCopyRestoreSuccessMessage(true, t)).toBe('已重新收录到本地')
    expect(buildUserAssetLocalCopyRestoreSuccessMessage(false, t)).toBe('当前浏览器已存在本地副本')
    expect(buildUserAssetLocalCopyRestoreErrorFallback(t)).toBe('重新收录到本地失败')
    expect(buildUserAssetLocalCopyBatchRestoreSuccessMessage({ restoredCount: 2, existingCount: 1 }, t)).toBe(
      '已重新收录 2 项本地副本，1 项当前浏览器已存在本地副本',
    )
    expect(buildUserAssetLocalCopyBatchRestoreSuccessMessage({ restoredCount: 0, existingCount: 3 }, t)).toBe(
      '所选资产当前浏览器中已存在本地副本',
    )
    expect(buildUserAssetLocalCopyBatchRestoreErrorMessage({
      restoredCount: 0,
      existingCount: 0,
      blockedCount: 2,
      failedCount: 0,
    }, t)).toBe('所选资产当前无法恢复到登记的本地存储，共 2 项受阻')
    expect(buildUserAssetLocalCopyBatchRestoreErrorMessage({
      restoredCount: 1,
      existingCount: 1,
      blockedCount: 2,
      failedCount: 3,
    }, t)).toBe('批量重新收录到本地时有 3 项失败；已重新收录 1 项，1 项已存在本地副本，2 项因目标存储不可用未恢复')
    expect(buildUserAssetLocalCopyBatchClearSuccessMessage({ clearedCount: 2, missingCount: 1 }, t)).toBe(
      '已清理 2 项本地副本，1 项当前浏览器未发现本地副本',
    )
    expect(buildUserAssetLocalCopyBatchClearSuccessMessage({ clearedCount: 0, missingCount: 3 }, t)).toBe(
      '当前浏览器未发现所选资产的本地副本',
    )
    expect(buildUserAssetLocalCopyBatchClearErrorMessage({
      clearedCount: 1,
      missingCount: 1,
      failedCount: 2,
    }, t)).toBe('批量清理本地副本时有 2 项失败；已清理 1 项，1 项未发现本地副本')
  })
})
