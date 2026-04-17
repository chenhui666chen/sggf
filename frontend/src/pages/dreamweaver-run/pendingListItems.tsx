import { Box, Button, Chip, ListItem, Stack, Typography } from '@mui/material'

import type { DreamweaverShotSnapshot } from '@/types/dreamweaver'

import {
  truncatePendingPromptText,
  type PendingPromptReviewShotState,
  type PendingVideoConfirmationJobState,
} from './pendingViewState'

type PendingVideoConfirmationJobItemProps = {
  itemKey: string
  shot: DreamweaverShotSnapshot | null
  state: PendingVideoConfirmationJobState
  onConfirm: (shotId: string) => void
  onEditPrompt: (shot: DreamweaverShotSnapshot) => void
}

const renderPendingVideoConfirmationJobHeader = (state: PendingVideoConfirmationJobState) => (
  <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
      {state.title}
    </Typography>
    <Chip size="small" label={state.statusLabel} color={state.statusColor} />
    {state.showConfirmedChip && <Chip size="small" label="已确认" color="primary" />}
    {state.requiresBridge && <Chip size="small" label={`桥接依赖: ${state.bridgeDependency || '-'}`} />}
  </Stack>
)

const renderPendingVideoConfirmationJobPromptSection = (state: PendingVideoConfirmationJobState) => {
  if (!state.hasPrompt) {
    return (
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        暂无提示词快照
      </Typography>
    )
  }

  return (
    <Box sx={{ mt: 0.5 }}>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
        首帧: {state.headPrompt ? truncatePendingPromptText(state.headPrompt, '…') : '-'}
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
        尾帧: {state.tailPrompt ? truncatePendingPromptText(state.tailPrompt, '…') : '-'}
      </Typography>
      {state.overridePrompt && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
          视频覆盖: {truncatePendingPromptText(state.overridePrompt, '…')}
        </Typography>
      )}
    </Box>
  )
}

export function PendingVideoConfirmationJobItem({
  itemKey,
  shot,
  state,
  onConfirm,
  onEditPrompt,
}: PendingVideoConfirmationJobItemProps) {
  return (
    <ListItem key={itemKey} disableGutters sx={{ px: 1, py: 0.75, borderBottom: '1px solid #f0f0f0', alignItems: 'flex-start' }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        {renderPendingVideoConfirmationJobHeader(state)}
        {state.desc && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
            {state.desc}
          </Typography>
        )}
        {renderPendingVideoConfirmationJobPromptSection(state)}
      </Box>

      <Box sx={{ pl: 1 }}>
        <Stack spacing={0.5} alignItems="flex-end">
          <Button size="small" variant="contained" onClick={() => onConfirm(state.shotId)} disabled={state.actionDisabled}>
            {state.actionLabel}
          </Button>
          <Button size="small" variant="outlined" onClick={() => shot && onEditPrompt(shot)} disabled={state.promptActionDisabled}>
            查看提示词
          </Button>
        </Stack>
      </Box>
    </ListItem>
  )
}

type PendingPromptReviewShotItemProps = {
  itemKey: string
  shot: DreamweaverShotSnapshot
  state: PendingPromptReviewShotState
  onEditPrompt: (shot: DreamweaverShotSnapshot) => void
}

const renderPendingPromptReviewShotHeader = (state: PendingPromptReviewShotState) => (
  <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
      {state.title}
    </Typography>
    {state.shotId && <Chip size="small" label={state.shotId} variant="outlined" />}
    {state.hasOverridePrompt && <Chip size="small" label="视频已覆盖" color="info" />}
  </Stack>
)

const renderPendingPromptReviewShotPromptSection = (state: PendingPromptReviewShotState) => (
  <>
    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
      首帧: {state.headPrompt ? truncatePendingPromptText(state.headPrompt) : '-'}
    </Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25, whiteSpace: 'pre-wrap' }}>
      尾帧: {state.tailPrompt ? truncatePendingPromptText(state.tailPrompt) : '-'}
    </Typography>
  </>
)

export function PendingPromptReviewShotItem({ itemKey, shot, state, onEditPrompt }: PendingPromptReviewShotItemProps) {
  return (
    <ListItem key={itemKey} disableGutters sx={{ px: 1, py: 0.75, borderBottom: '1px solid #f0f0f0', alignItems: 'flex-start' }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        {renderPendingPromptReviewShotHeader(state)}
        {renderPendingPromptReviewShotPromptSection(state)}
      </Box>
      <Box sx={{ pl: 1 }}>
        <Button size="small" variant="outlined" onClick={() => onEditPrompt(shot)} disabled={state.promptActionDisabled}>
          编辑提示词
        </Button>
      </Box>
    </ListItem>
  )
}
