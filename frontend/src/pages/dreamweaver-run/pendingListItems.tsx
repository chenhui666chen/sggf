import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

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

const renderPendingVideoConfirmationJobHeader = (state: PendingVideoConfirmationJobState, t?: TFunction) => (
  <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
      {state.title}
    </Typography>
    <Chip size="small" label={state.statusLabel} color={state.statusColor} />
    {state.showConfirmedChip && <Chip size="small" label={t ? t('dreamweaverRun.pendingConfirmed') : '已确认'} color="primary" />}
    {state.requiresBridge && (
      <Chip size="small" label={t ? t('dreamweaverRun.pendingBridgeDependency', { dep: state.bridgeDependency || '-' }) : `桥接依赖: ${state.bridgeDependency || '-'}`} />
    )}
  </Stack>
)

const renderPendingVideoConfirmationJobPromptSection = (state: PendingVideoConfirmationJobState, t?: TFunction) => {
  if (!state.hasPrompt) {
    return (
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        {t ? t('dreamweaverRun.pendingNoPromptSnapshot') : '暂无提示词快照'}
      </Typography>
    )
  }

  return (
    <Box sx={{ mt: 0.5 }}>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
        {t ? t('dreamweaverRun.pendingHeadFrame', { text: state.headPrompt ? truncatePendingPromptText(state.headPrompt, '…') : '-' }) : `首帧: ${state.headPrompt ? truncatePendingPromptText(state.headPrompt, '…') : '-'}`}
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
        {t ? t('dreamweaverRun.pendingTailFrame', { text: state.tailPrompt ? truncatePendingPromptText(state.tailPrompt, '…') : '-' }) : `尾帧: ${state.tailPrompt ? truncatePendingPromptText(state.tailPrompt, '…') : '-'}`}
      </Typography>
      {state.overridePrompt && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
          {t ? t('dreamweaverRun.pendingVideoOverride', { text: truncatePendingPromptText(state.overridePrompt, '…') }) : `视频覆盖: ${truncatePendingPromptText(state.overridePrompt, '…')}`}
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
  const { t } = useTranslation()
  return (
    <ListItem key={itemKey} disableGutters sx={{ px: 1, py: 0.75, borderBottom: '1px solid', borderBottomColor: 'divider', alignItems: 'flex-start' }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        {renderPendingVideoConfirmationJobHeader(state, t)}
        {state.desc && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
            {state.desc}
          </Typography>
        )}
        {renderPendingVideoConfirmationJobPromptSection(state, t)}
      </Box>

      <Box sx={{ pl: 1 }}>
        <Stack spacing={0.5} alignItems="flex-end">
          <Button size="small" variant="contained" onClick={() => onConfirm(state.shotId)} disabled={state.actionDisabled}>
            {state.actionLabel}
          </Button>
          <Button size="small" variant="outlined" onClick={() => shot && onEditPrompt(shot)} disabled={state.promptActionDisabled}>
            {t('dreamweaverRun.pendingViewPrompt')}
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

const renderPendingPromptReviewShotHeader = (state: PendingPromptReviewShotState, t?: TFunction) => (
  <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
      {state.title}
    </Typography>
    {state.shotId && <Chip size="small" label={state.shotId} variant="outlined" />}
    {state.hasOverridePrompt && <Chip size="small" label={t ? t('dreamweaverRun.pendingVideoOverridden') : '视频已覆盖'} color="info" />}
  </Stack>
)

const renderPendingPromptReviewShotPromptSection = (state: PendingPromptReviewShotState, t?: TFunction) => (
  <>
    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
      {t ? t('dreamweaverRun.pendingHeadFrame', { text: state.headPrompt ? truncatePendingPromptText(state.headPrompt) : '-' }) : `首帧: ${state.headPrompt ? truncatePendingPromptText(state.headPrompt) : '-'}`}
    </Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25, whiteSpace: 'pre-wrap' }}>
      {t ? t('dreamweaverRun.pendingTailFrame', { text: state.tailPrompt ? truncatePendingPromptText(state.tailPrompt) : '-' }) : `尾帧: ${state.tailPrompt ? truncatePendingPromptText(state.tailPrompt) : '-'}`}
    </Typography>
  </>
)

export function PendingPromptReviewShotItem({ itemKey, shot, state, onEditPrompt }: PendingPromptReviewShotItemProps) {
  const { t } = useTranslation()
  return (
    <ListItem key={itemKey} disableGutters sx={{ px: 1, py: 0.75, borderBottom: '1px solid', borderBottomColor: 'divider', alignItems: 'flex-start' }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        {renderPendingPromptReviewShotHeader(state, t)}
        {renderPendingPromptReviewShotPromptSection(state, t)}
      </Box>
      <Box sx={{ pl: 1 }}>
        <Button size="small" variant="outlined" onClick={() => onEditPrompt(shot)} disabled={state.promptActionDisabled}>
          {t('dreamweaverRun.pendingEditPrompt')}
        </Button>
      </Box>
    </ListItem>
  )
}
