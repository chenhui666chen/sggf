import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
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
      <DialogTitle>{t('audiobook.cosyVoiceCloneRecordDialog.title')}</DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" sx={{ mb: 1 }}>
          {strictTranscriptMode
            ? t('audiobook.cosyVoiceCloneRecordDialog.strictPrompt', { text: transcriptText })
            : t('audiobook.cosyVoiceCloneRecordDialog.samplePrompt')}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {strictTranscriptMode
            ? t('audiobook.cosyVoiceCloneRecordDialog.strictHint')
            : t('audiobook.cosyVoiceCloneRecordDialog.freeHint')}
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
              {t('audiobook.cosyVoiceCloneRecordDialog.statsTitle')}
            </Typography>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1}
              sx={{ mb: 1.25 }}
            >
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  {t('audiobook.cosyVoiceCloneRecordDialog.recordedDuration')}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {formatRecordDuration(recordElapsedSeconds)}
                </Typography>
              </Box>
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  {t('audiobook.cosyVoiceCloneRecordDialog.suggestedDuration')}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {t('audiobook.cosyVoiceCloneRecordDialog.targetSeconds', { total: RECORD_TARGET_SECONDS })}
                </Typography>
              </Box>
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  {t('audiobook.cosyVoiceCloneRecordDialog.progress')}
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
          {t('action.close')}
        </Button>
        <Button
          variant="contained"
          color={cloneRecording ? 'error' : 'primary'}
          onClick={cloneRecording ? onStopCloneRecording : onStartCloneRecording}
          disabled={cloneLoading || cloneUploading}
        >
          {cloneRecording
            ? t('audiobook.cosyVoiceCloneRecordDialog.stopAndUpload')
            : t('audiobook.cosyVoiceCloneRecordDialog.startRecording')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default CosyVoiceCloneRecordDialog
