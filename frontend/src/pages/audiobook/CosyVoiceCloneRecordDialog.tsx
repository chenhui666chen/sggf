import { useEffect, useMemo, useState } from 'react'

import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Stack,
  Typography,
} from '@mui/material'

const RECORD_TARGET_SECONDS = 10

const formatRecordDuration = (seconds: number) => {
  const safeSeconds = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(safeSeconds / 60)
  const remainingSeconds = safeSeconds % 60
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}

interface CosyVoiceCloneRecordDialogProps {
  open: boolean
  cloneRecording: boolean
  cloneLoading: boolean
  cloneUploading: boolean
  strictTranscriptMode?: boolean
  transcriptText?: string
  onClose: () => void
  onStartCloneRecording: () => void
  onStopCloneRecording: () => void
}

const CosyVoiceCloneRecordDialog = ({
  open,
  cloneRecording,
  cloneLoading,
  cloneUploading,
  strictTranscriptMode = false,
  transcriptText = '',
  onClose,
  onStartCloneRecording,
  onStopCloneRecording,
}: CosyVoiceCloneRecordDialogProps) => {
  const [recordElapsedSeconds, setRecordElapsedSeconds] = useState(0)
  const recordProgress = useMemo(
    () => Math.min(100, Math.round((recordElapsedSeconds / RECORD_TARGET_SECONDS) * 100)),
    [recordElapsedSeconds],
  )

  useEffect(() => {
    if (!cloneRecording) {
      setRecordElapsedSeconds(0)
      return undefined
    }

    setRecordElapsedSeconds(0)
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      setRecordElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [cloneRecording])

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      disableEscapeKeyDown={cloneRecording}
    >
      <DialogTitle>录音朗读提示</DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" sx={{ mb: 1 }}>
          {strictTranscriptMode
            ? `必须逐字朗读下方内容：“${transcriptText}”`
            : '朗读示例（约10秒）：“时间会缓和所有的悲伤，当你的悲伤被安抚以后，你就会因为认识过我而感到满足。”'}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {strictTranscriptMode
            ? '不要随机朗读其他内容，StepAudio 会用 ASR 校验录音与参考音频逐字内容是否一致。'
            : '也可以随机读其他内容。'}
        </Typography>

        {cloneRecording && (
          <Box
            sx={{
              mt: 2,
              p: 1.5,
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              backgroundColor: 'background.default',
            }}
          >
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
              录音统计
            </Typography>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1}
              sx={{ mb: 1.25 }}
            >
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  已录时长
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {formatRecordDuration(recordElapsedSeconds)}
                </Typography>
              </Box>
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  建议时长
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {RECORD_TARGET_SECONDS} 秒
                </Typography>
              </Box>
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  完成度
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {recordProgress}%
                </Typography>
              </Box>
            </Stack>
            <LinearProgress
              variant="determinate"
              value={recordProgress}
              sx={{ height: 8, borderRadius: 1 }}
            />
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={cloneRecording}>
          关闭
        </Button>
        <Button
          variant="contained"
          color={cloneRecording ? 'error' : 'primary'}
          onClick={cloneRecording ? onStopCloneRecording : onStartCloneRecording}
          disabled={cloneLoading || cloneUploading}
        >
          {cloneRecording ? '结束录音并上传' : '开始录音'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default CosyVoiceCloneRecordDialog
