import { describe, expect, it } from 'vitest'

import {
  buildActivateBatchUserAssetCommand,
  buildArchiveBatchUserAssetCommand,
  buildClearLocalCopyBatchUserAssetCommand,
  buildFavoriteBatchUserAssetCommand,
  buildRestoreLocalCopyBatchUserAssetCommand,
} from '../user-assets/userAssetListPresentation'
import { buildUserAssetBatchToolbarPresentation } from '../user-assets/userAssetBatchToolbarPresentation'

describe('userAssetBatchToolbarPresentation', () => {
  it('builds summary chips and actions for active selection', () => {
    const presentation = buildUserAssetBatchToolbarPresentation({
      selection: {
        selectedCount: 2,
        selectedLocalMirrorCount: 1,
        visibleCount: 5,
        hasSelection: true,
        allVisibleSelected: false,
      },
      batchCommands: [
        buildFavoriteBatchUserAssetCommand(),
        buildArchiveBatchUserAssetCommand(),
        buildRestoreLocalCopyBatchUserAssetCommand(),
        buildClearLocalCopyBatchUserAssetCommand(),
      ],
    })

    expect(presentation.summaryChips).toEqual([
      {
        key: 'asset-selected-count',
        color: 'primary',
        variant: 'filled',
        label: '已选 2',
      },
      {
        key: 'asset-visible-count',
        variant: 'outlined',
        label: '可选 5 项',
      },
    ])
    expect(presentation.selectAllAction).toEqual({
      key: 'toggle-select-all-assets',
      label: '全选当前结果',
      disabled: false,
      variant: 'outlined',
    })
    expect(presentation.clearSelectionAction).toEqual({
      key: 'clear-selected-assets',
      label: '清空选择',
      disabled: false,
      variant: 'outlined',
    })
    expect(presentation.batchActions.map((action) => action.label)).toEqual([
      '设为重点',
      '归档',
      '重新收录到本地',
      '清理本地副本',
    ])
    expect(presentation.batchActions.every((action) => action.disabled === false)).toBe(true)
  })

  it('disables local-copy actions when selected assets have no local mirror copy candidates', () => {
    const presentation = buildUserAssetBatchToolbarPresentation({
      selection: {
        selectedCount: 2,
        selectedLocalMirrorCount: 0,
        visibleCount: 3,
        hasSelection: true,
        allVisibleSelected: true,
      },
      batchCommands: [
        buildRestoreLocalCopyBatchUserAssetCommand(),
        buildClearLocalCopyBatchUserAssetCommand(),
      ],
    })

    expect(presentation.batchActions[0]).toMatchObject({
      label: '重新收录到本地',
      disabled: true,
    })
    expect(presentation.batchActions[1]).toMatchObject({
      label: '清理本地副本',
      disabled: true,
    })
  })

  it('disables clear and batch actions when no selection or request is submitting', () => {
    const presentation = buildUserAssetBatchToolbarPresentation({
      selection: {
        selectedCount: 0,
        selectedLocalMirrorCount: 0,
        visibleCount: 3,
        hasSelection: false,
        allVisibleSelected: true,
      },
      batchSubmitting: true,
      batchCommands: [buildActivateBatchUserAssetCommand()],
    })

    expect(presentation.summaryChips[0]).toEqual({
      key: 'asset-selected-count',
      color: 'default',
      variant: 'outlined',
      label: '已选 0',
    })
    expect(presentation.summaryChips[1]).toEqual({
      key: 'asset-visible-count',
      variant: 'outlined',
      label: '当前结果已全选',
    })
    expect(presentation.selectAllAction.disabled).toBe(true)
    expect(presentation.selectAllAction.label).toBe('取消全选')
    expect(presentation.clearSelectionAction.disabled).toBe(true)
    expect(presentation.batchActions[0]).toMatchObject({
      label: '恢复活跃',
      disabled: true,
    })
  })
})
