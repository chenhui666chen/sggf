import {
  Button,
  Card,
  CardContent,
  Chip,
  Stack,
} from '@mui/material'

import { buildUserAssetBatchToolbarPresentation } from './userAssetBatchToolbarPresentation'
import type {
  UserAssetBatchActionCommand,
  UserAssetListSelectionState,
} from './userAssetListPresentation'

export type UserAssetBatchToolbarProps = {
  selection: Pick<
    UserAssetListSelectionState,
    'selectedCount' | 'selectedLocalMirrorCount' | 'visibleCount' | 'hasSelection' | 'allVisibleSelected'
  >
  batchCommands: UserAssetBatchActionCommand[]
  batchSubmitting?: boolean
  onToggleSelectAll: () => void
  onClearSelection: () => void
  onRunBatchAction: (command: UserAssetBatchActionCommand) => void
}

export default function UserAssetBatchToolbar(props: UserAssetBatchToolbarProps) {
  const {
    selection,
    batchCommands,
    batchSubmitting = false,
    onToggleSelectAll,
    onClearSelection,
    onRunBatchAction,
  } = props

  const presentation = buildUserAssetBatchToolbarPresentation({
    selection,
    batchSubmitting,
    batchCommands,
  })

  return (
    <Card variant="outlined" sx={{ borderRadius: 3 }}>
      <CardContent>
        <Stack direction={{ xs: 'column', lg: 'row' }} spacing={1.5} justifyContent="space-between">
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap">
            {presentation.summaryChips.map((chip) => (
              <Chip
                key={chip.key}
                size="small"
                color={chip.color}
                variant={chip.variant}
                label={chip.label}
              />
            ))}
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap">
            <Button
              size="small"
              variant={presentation.selectAllAction.variant}
              onClick={onToggleSelectAll}
              disabled={presentation.selectAllAction.disabled}
            >
              {presentation.selectAllAction.label}
            </Button>
            <Button
              size="small"
              variant={presentation.clearSelectionAction.variant}
              onClick={onClearSelection}
              disabled={presentation.clearSelectionAction.disabled}
            >
              {presentation.clearSelectionAction.label}
            </Button>
            {presentation.batchActions.map((action) => (
              <Button
                key={action.key}
                size="small"
                variant={action.variant}
                onClick={() => action.command && onRunBatchAction(action.command)}
                disabled={action.disabled}
              >
                {action.label}
              </Button>
            ))}
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  )
}
