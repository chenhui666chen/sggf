import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

import { STAGE_STATUS_LABELS } from './constants'
import { audiobookColors } from './audiobookTheme'
import { getPromptAudioQualitySummary } from './stageMetricsUtils'
import type {
  StageConfig,
  StageInfo,
} from './types'

export interface StageMetricsDialogData {
  stage: StageConfig
  info: StageInfo
}

interface StageMetricsDialogProps {
  open: boolean
  data: StageMetricsDialogData | null
  onClose: () => void
}

const PromptAudioQualitySummaryPanel = ({
  metrics,
}: {
  metrics: Record<string, unknown> | undefined
}) => {
  const { t } = useTranslation()
  const promptAudioQuality = getPromptAudioQualitySummary(metrics)
  if (!promptAudioQuality) {
    return null
  }

  return (
    <Paper
      variant="outlined"
      sx={{ p: 1.25, backgroundColor: audiobookColors.surfaceSubtle }}
    >
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        {t('audiobook.stageMetricsDialog.qualityWritebackTitle')}
      </Typography>
      <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mb: 1 }}>
        <Chip size="small" label={t('audiobook.stageMetricsDialog.segmentsChip', { total: promptAudioQuality.coverage.segmentsCount })} />
        <Chip size="small" label={t('audiobook.stageMetricsDialog.audioSegmentsChip', { total: promptAudioQuality.coverage.audioSegmentsCount })} />
        <Chip
          size="small"
          label={t('audiobook.stageMetricsDialog.missingAudioChip', { total: promptAudioQuality.coverage.missingAudioCount })}
          color={promptAudioQuality.coverage.missingAudioCount > 0 ? 'warning' : 'default'}
          variant={promptAudioQuality.coverage.missingAudioCount > 0 ? 'outlined' : 'filled'}
        />
        <Chip size="small" label={t('audiobook.stageMetricsDialog.promptSnapshotChip', { total: promptAudioQuality.coverage.providerPromptSnapshotCount })} />
        <Chip size="small" label={t('audiobook.stageMetricsDialog.tagStrategyChip', { total: promptAudioQuality.coverage.inlineTagStrategyCount })} />
        <Chip
          size="small"
          label={t('audiobook.stageMetricsDialog.manualReviewPendingChip', { total: promptAudioQuality.coverage.manualReviewPendingCount })}
          color={promptAudioQuality.coverage.manualReviewPendingCount > 0 ? 'primary' : 'default'}
          variant="outlined"
        />
      </Stack>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
        {promptAudioQuality.models.map((model) => (
          <Box
            key={model.model}
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: 'minmax(160px, 1.2fr) minmax(0, 2fr)' },
              gap: 0.75,
              alignItems: 'center',
            }}
          >
            <Typography variant="caption" sx={{ fontWeight: 700, wordBreak: 'break-word' }}>
              {model.model}
            </Typography>
            <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
              {model.modelFamily && <Chip size="small" label={model.modelFamily} />}
              <Chip size="small" label={t('audiobook.stageMetricsDialog.segmentsChip', { total: model.segmentsCount })} variant="outlined" />
              <Chip size="small" label={t('audiobook.stageMetricsDialog.audioChip', { total: model.audioSegmentsCount })} variant="outlined" />
              {model.missingAudioCount > 0 && (
                <Chip size="small" label={t('audiobook.stageMetricsDialog.missingChip', { total: model.missingAudioCount })} color="warning" variant="outlined" />
              )}
              <Chip size="small" label={t('audiobook.stageMetricsDialog.snapshotChip', { total: model.providerPromptSnapshotCount })} variant="outlined" />
              <Chip size="small" label={t('audiobook.stageMetricsDialog.tagChip', { total: model.inlineTagStrategyCount })} variant="outlined" />
              {model.useTagParserCount > 0 && (
                <Chip size="small" label={t('audiobook.stageMetricsDialog.parserChip', { total: model.useTagParserCount })} color="primary" variant="outlined" />
              )}
              {model.tagCount > 0 && <Chip size="small" label={t('audiobook.stageMetricsDialog.tagCountChip', { total: model.tagCount })} variant="outlined" />}
              {model.manualReviewSegmentIndices.length > 0 && (
                <Chip
                  size="small"
                  label={t('audiobook.stageMetricsDialog.reviewChip', {
                    indices: model.manualReviewSegmentIndices.map((item) => item + 1).join(', #'),
                  })}
                  color="primary"
                  variant="outlined"
                />
              )}
            </Stack>
          </Box>
        ))}
      </Box>
    </Paper>
  )
}

const StageMetricsDialog = ({
  open,
  data,
  onClose,
}: StageMetricsDialogProps) => {
  const { t } = useTranslation()
  return (
  <Dialog
    open={open}
    onClose={onClose}
    maxWidth="md"
    fullWidth
  >
    <DialogTitle>
      {data
        ? t('audiobook.stageMetricsDialog.stageResultTitle', { name: data.stage.name })
        : t('audiobook.stageMetricsDialog.stageResult')}
    </DialogTitle>
    <DialogContent dividers>
      {!data ? (
        <Typography variant="body2" color="text.secondary">
          {t('audiobook.stageMetricsDialog.noStageData')}
        </Typography>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            {t('audiobook.stageMetricsDialog.statusLabel', { status: t(STAGE_STATUS_LABELS[data.info.status]) })}
          </Typography>
          {data.info.message && (
            <Typography variant="body2">{t('audiobook.stageMetricsDialog.messageLabel', { message: data.info.message })}</Typography>
          )}
          {data.info.start_time && (
            <Typography variant="body2" color="text.secondary">
              {t('audiobook.stageMetricsDialog.startTimeLabel', { time: data.info.start_time })}
            </Typography>
          )}
          {data.info.end_time && (
            <Typography variant="body2" color="text.secondary">
              {t('audiobook.stageMetricsDialog.endTimeLabel', { time: data.info.end_time })}
            </Typography>
          )}
          {data.info.error_message && (
            <Alert severity="error">{data.info.error_message}</Alert>
          )}
          <PromptAudioQualitySummaryPanel metrics={data.info.metrics} />
          <Paper
            variant="outlined"
            sx={{ p: 1, backgroundColor: audiobookColors.surfaceSubtle }}
          >
            <Box
              component="pre"
              sx={{ m: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}
            >
              {JSON.stringify(data.info.metrics, null, 2)}
            </Box>
          </Paper>
        </Box>
      )}
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose}>{t('action.close')}</Button>
    </DialogActions>
  </Dialog>
  )
}

export default StageMetricsDialog
