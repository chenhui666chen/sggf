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
        Prompt→Audio 质量回写
      </Typography>
      <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mb: 1 }}>
        <Chip size="small" label={`片段 ${promptAudioQuality.coverage.segmentsCount}`} />
        <Chip size="small" label={`已产音频 ${promptAudioQuality.coverage.audioSegmentsCount}`} />
        <Chip
          size="small"
          label={`缺失音频 ${promptAudioQuality.coverage.missingAudioCount}`}
          color={promptAudioQuality.coverage.missingAudioCount > 0 ? 'warning' : 'default'}
          variant={promptAudioQuality.coverage.missingAudioCount > 0 ? 'outlined' : 'filled'}
        />
        <Chip size="small" label={`Prompt 快照 ${promptAudioQuality.coverage.providerPromptSnapshotCount}`} />
        <Chip size="small" label={`标签策略 ${promptAudioQuality.coverage.inlineTagStrategyCount}`} />
        <Chip
          size="small"
          label={`待人工验收 ${promptAudioQuality.coverage.manualReviewPendingCount}`}
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
              <Chip size="small" label={`片段 ${model.segmentsCount}`} variant="outlined" />
              <Chip size="small" label={`音频 ${model.audioSegmentsCount}`} variant="outlined" />
              {model.missingAudioCount > 0 && (
                <Chip size="small" label={`缺失 ${model.missingAudioCount}`} color="warning" variant="outlined" />
              )}
              <Chip size="small" label={`快照 ${model.providerPromptSnapshotCount}`} variant="outlined" />
              <Chip size="small" label={`标签 ${model.inlineTagStrategyCount}`} variant="outlined" />
              {model.useTagParserCount > 0 && (
                <Chip size="small" label={`Parser ${model.useTagParserCount}`} color="primary" variant="outlined" />
              )}
              {model.tagCount > 0 && <Chip size="small" label={`Tag ${model.tagCount}`} variant="outlined" />}
              {model.manualReviewSegmentIndices.length > 0 && (
                <Chip
                  size="small"
                  label={`验收 #${model.manualReviewSegmentIndices.map((item) => item + 1).join(', #')}`}
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
}: StageMetricsDialogProps) => (
  <Dialog
    open={open}
    onClose={onClose}
    maxWidth="md"
    fullWidth
  >
    <DialogTitle>
      {data ? `阶段结果：${data.stage.name}` : '阶段结果'}
    </DialogTitle>
    <DialogContent dividers>
      {!data ? (
        <Typography variant="body2" color="text.secondary">
          暂无阶段数据
        </Typography>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            状态：{STAGE_STATUS_LABELS[data.info.status]}
          </Typography>
          {data.info.message && (
            <Typography variant="body2">提示：{data.info.message}</Typography>
          )}
          {data.info.start_time && (
            <Typography variant="body2" color="text.secondary">
              开始时间：{data.info.start_time}
            </Typography>
          )}
          {data.info.end_time && (
            <Typography variant="body2" color="text.secondary">
              结束时间：{data.info.end_time}
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
      <Button onClick={onClose}>关闭</Button>
    </DialogActions>
  </Dialog>
)

export default StageMetricsDialog
