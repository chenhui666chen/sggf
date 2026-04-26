import type {
  ButtonProps,
  ChipProps,
} from '@mui/material'

import type {
  UserAssetBatchActionCommand,
  UserAssetListSelectionState,
} from './userAssetListPresentation'

export type UserAssetBatchToolbarChipSpec = {
  key: string
  label: string
  color?: ChipProps['color']
  variant?: ChipProps['variant']
}

export type UserAssetBatchToolbarActionSpec = {
  key: string
  label: string
  disabled: boolean
  variant?: ButtonProps['variant']
  command?: UserAssetBatchActionCommand
}

export type UserAssetBatchToolbarPresentation = {
  summaryChips: UserAssetBatchToolbarChipSpec[]
  selectAllAction: UserAssetBatchToolbarActionSpec
  clearSelectionAction: UserAssetBatchToolbarActionSpec
  batchActions: UserAssetBatchToolbarActionSpec[]
}

type BuildUserAssetBatchToolbarPresentationOptions = {
  selection: Pick<
    UserAssetListSelectionState,
    'selectedCount' | 'selectedLocalMirrorCount' | 'visibleCount' | 'hasSelection' | 'allVisibleSelected'
  >
  batchSubmitting?: boolean
  batchCommands: UserAssetBatchActionCommand[]
}

function isBatchActionDisabled(
  command: UserAssetBatchActionCommand,
  selection: BuildUserAssetBatchToolbarPresentationOptions['selection'],
  batchSubmitting: boolean,
): boolean {
  if (batchSubmitting) {
    return true
  }

  if (command.kind === 'clear_local_copy') {
    return selection.selectedLocalMirrorCount === 0
  }

  if (command.kind === 'restore_local_copy') {
    return selection.selectedLocalMirrorCount === 0
  }

  return !selection.hasSelection
}

export function buildUserAssetBatchToolbarPresentation(
  options: BuildUserAssetBatchToolbarPresentationOptions,
): UserAssetBatchToolbarPresentation {
  const {
    selection,
    batchSubmitting = false,
    batchCommands,
  } = options

  return {
    summaryChips: [
      {
        key: 'asset-selected-count',
        color: selection.hasSelection ? 'primary' : 'default',
        variant: selection.hasSelection ? 'filled' : 'outlined',
        label: `已选 ${selection.selectedCount}`,
      },
      {
        key: 'asset-visible-count',
        variant: 'outlined',
        label: selection.allVisibleSelected ? '当前结果已全选' : `可选 ${selection.visibleCount} 项`,
      },
    ],
    selectAllAction: {
      key: 'toggle-select-all-assets',
      label: selection.allVisibleSelected ? '取消全选' : '全选当前结果',
      disabled: batchSubmitting,
      variant: 'outlined',
    },
    clearSelectionAction: {
      key: 'clear-selected-assets',
      label: '清空选择',
      disabled: batchSubmitting || !selection.hasSelection,
      variant: 'outlined',
    },
    batchActions: batchCommands.map((command) => ({
      key: `asset-batch-action-${command.kind}-${command.label}`,
      label: command.label,
      disabled: isBatchActionDisabled(command, selection, batchSubmitting),
      variant: 'outlined',
      command,
    })),
  }
}
