import type {
  ButtonProps,
  ChipProps,
} from '@mui/material'
import type { TFunction } from 'i18next'

import type {
  UserAssetBatchActionCommand,
  UserAssetListSelectionState,
} from './userAssetListPresentation'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

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
  t?: TFunction,
): UserAssetBatchToolbarPresentation {
  const translate = t ?? DEFAULT_TRANSLATE
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
        label: translate('userAsset.batch.selectedCount', { count: selection.selectedCount }),
      },
      {
        key: 'asset-visible-count',
        variant: 'outlined',
        label: selection.allVisibleSelected
          ? translate('userAsset.batch.allVisibleSelected')
          : translate('userAsset.batch.visibleCount', { count: selection.visibleCount }),
      },
    ],
    selectAllAction: {
      key: 'toggle-select-all-assets',
      label: selection.allVisibleSelected
        ? translate('userAsset.batch.unselectAll')
        : translate('userAsset.batch.selectAll'),
      disabled: batchSubmitting,
      variant: 'outlined',
    },
    clearSelectionAction: {
      key: 'clear-selected-assets',
      label: translate('userAsset.batch.clearSelection'),
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
