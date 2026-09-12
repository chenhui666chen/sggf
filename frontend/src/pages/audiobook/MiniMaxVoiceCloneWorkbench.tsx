import { useMemo, useState, type ChangeEvent } from 'react'

import { useTranslation } from 'react-i18next'

import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import MicIcon from '@mui/icons-material/Mic'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Paper,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { audiobookButtonSx } from './audiobookTheme'
import CosyVoiceCloneRecordDialog from './CosyVoiceCloneRecordDialog'
import type { TtsModel, VoicePreset } from './types'
import { useCosyVoiceCloneRecording } from './useCosyVoiceCloneRecording'
import {
  convertRecordedAudioBlobToWavFile,
  isMimoCloneSupportedAudioFile,
  summarizeAudioFile,
} from './voiceCloneAudioUtils'

interface MiniMaxVoiceCloneWorkbenchProps {
  ttsModel: TtsModel
  customVoicePresets: VoicePreset[]
  previewingVoiceId: string | null
  onPreviewCustomVoice: (voice: VoicePreset, model?: TtsModel) => void
  onChanged: () => void
}

interface CreatedClonePreview {
  voiceId: string
  audioUrl: string
  billingNotice: string
}

const MINIMAX_PREVIEW_PRICE_KEYS: Record<string, string> = {
  'minimax-speech-2.8-hd': 'audiobook.minimaxVoiceClone.previewPriceHd',
  'minimax-speech-2.8-turbo': 'audiobook.minimaxVoiceClone.previewPriceTurbo',
}

const MiniMaxVoiceCloneWorkbench = ({
  ttsModel,
  customVoicePresets,
  previewingVoiceId,
  onPreviewCustomVoice,
  onChanged,
}: MiniMaxVoiceCloneWorkbenchProps) => {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [sampleText, setSampleText] = useState('')
  const [sampleFile, setSampleFile] = useState<File | null>(null)
  const [creating, setCreating] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [recordDialogOpen, setRecordDialogOpen] = useState(false)
  const [billingConfirmOpen, setBillingConfirmOpen] = useState(false)
  const [createdPreview, setCreatedPreview] = useState<CreatedClonePreview | null>(null)
  const [removeTarget, setRemoveTarget] = useState<VoicePreset | null>(null)
  const [removing, setRemoving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const minimaxPresets = useMemo(
    () => customVoicePresets.filter(
      (preset) => preset.provider === 'minimax' || preset.id.startsWith('mmx_'),
    ),
    [customVoicePresets],
  )
  const busy = creating || uploading || recording
  const previewPrice = t(MINIMAX_PREVIEW_PRICE_KEYS[ttsModel] || 'audiobook.minimaxVoiceClone.previewPriceUnknown')
  const sampleSummary = sampleFile ? summarizeAudioFile(sampleFile) : ''
  const canCreate = Boolean(name.trim() && sampleText.trim() && sampleFile)

  const resetMessages = () => {
    setMessage(null)
    setError(null)
  }

  const handleUploadAudio = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setUploading(true)
    resetMessages()
    try {
      if (!isMimoCloneSupportedAudioFile(file)) {
        throw new Error(t('audiobook.minimaxVoiceClone.sampleFormatError'))
      }
      setSampleFile(file)
      setMessage(t('audiobook.minimaxVoiceClone.sampleSelectedNotice'))
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.minimaxVoiceClone.sampleSelectFailed')))
    } finally {
      setUploading(false)
    }
  }

  const uploadRecordedAudio = async (blob: Blob) => {
    setRecordDialogOpen(false)
    setUploading(true)
    resetMessages()
    try {
      const file = await convertRecordedAudioBlobToWavFile(blob)
      setSampleFile(file)
      setMessage(t('audiobook.minimaxVoiceClone.wavConvertedNotice'))
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.minimaxVoiceClone.wavConvertFailed')))
    } finally {
      setUploading(false)
    }
  }

  const {
    handleStartCloneRecording,
    handleStopCloneRecording,
  } = useCosyVoiceCloneRecording({
    cloneLoading: creating,
    cloneUploading: uploading,
    cloneRecording: recording,
    setCloneRecording: setRecording,
    onResetCloneMessages: resetMessages,
    onCloneError: setError,
    onUploadRecordedCloneAudio: uploadRecordedAudio,
  })

  const handleOpenRecordDialog = () => {
    resetMessages()
    if (!sampleText.trim()) {
      setError(t('audiobook.minimaxVoiceClone.transcriptRequiredBeforeRecord'))
      return
    }
    setRecordDialogOpen(true)
  }

  const handleRequestCreate = () => {
    resetMessages()
    if (!name.trim()) {
      setError(t('audiobook.minimaxVoiceClone.nameRequired'))
      return
    }
    if (!sampleText.trim()) {
      setError(t('audiobook.minimaxVoiceClone.transcriptRequired'))
      return
    }
    if (!sampleFile) {
      setError(t('audiobook.minimaxVoiceClone.sampleRequired'))
      return
    }
    setBillingConfirmOpen(true)
  }

  const handleConfirmCreate = async () => {
    if (!sampleFile) return
    setBillingConfirmOpen(false)
    setCreating(true)
    resetMessages()
    try {
      const response = await apiClient.createMiniMaxVoiceCloneFromFile({
        model: ttsModel,
        name: name.trim(),
        sampleText: sampleText.trim(),
        file: sampleFile,
      })
      const payload = response.data
      const audioUrl = payload.preview_audio_data_base64
        ? `data:${payload.preview_audio_mime_type || 'audio/mpeg'};base64,${payload.preview_audio_data_base64}`
        : payload.preview_audio_url || ''
      setCreatedPreview({
        voiceId: payload.voice_id,
        audioUrl,
        billingNotice: payload.billing_notice,
      })
      setName('')
      setSampleText('')
      setSampleFile(null)
      setMessage(t('audiobook.minimaxVoiceClone.cloneCreatedNotice'))
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.minimaxVoiceClone.cloneCreateFailed')))
    } finally {
      setCreating(false)
    }
  }

  const handleRemove = async () => {
    if (!removeTarget) return
    setRemoving(true)
    resetMessages()
    try {
      await apiClient.removeMiniMaxVoiceClone(removeTarget.id)
      setMessage(t('audiobook.minimaxVoiceClone.cloneRemovedNotice'))
      setRemoveTarget(null)
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.minimaxVoiceClone.cloneRemoveFailed')))
    } finally {
      setRemoving(false)
    }
  }

  return (
    <Paper variant="outlined" sx={{ mb: 1, p: { xs: 1.5, md: 2 } }}>
      <Box sx={{ display: 'grid', gap: 0.75, mb: 1.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
          {t('audiobook.minimaxVoiceClone.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
          {t('audiobook.minimaxVoiceClone.intro')}
        </Typography>
        <Alert severity="warning">
          {t('audiobook.minimaxVoiceClone.previewBillingWarning', { previewPrice })}
        </Alert>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: 'minmax(180px, 0.7fr) minmax(280px, 1.3fr)' },
          gap: 1.25,
          mb: 1.25,
        }}
      >
        <TextField
          label={t('audiobook.minimaxVoiceClone.nameLabel')}
          value={name}
          onChange={(event) => setName(event.target.value)}
          size="small"
          fullWidth
          disabled={busy}
        />
        <TextField
          label={t('audiobook.minimaxVoiceClone.sampleTextLabel')}
          value={sampleText}
          onChange={(event) => setSampleText(event.target.value)}
          size="small"
          fullWidth
          multiline
          minRows={2}
          disabled={busy}
        />
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1.25 }}>
        <Button
          variant="outlined"
          disabled={busy}
          onClick={handleOpenRecordDialog}
          startIcon={<MicIcon />}
          sx={audiobookButtonSx.neutralOutlined}
        >
          {t('audiobook.minimaxVoiceClone.record')}
        </Button>
        <Button
          variant="outlined"
          component="label"
          disabled={busy}
          startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : <UploadFileIcon />}
          sx={audiobookButtonSx.brandOutlined}
        >
          {uploading ? t('audiobook.minimaxVoiceClone.uploadingText') : t('audiobook.minimaxVoiceClone.uploadAudio')}
          <input
            type="file"
            hidden
            accept=".mp3,.wav,audio/mpeg,audio/wav"
            onChange={handleUploadAudio}
          />
        </Button>
        <Button
          variant="contained"
          disabled={busy || !canCreate}
          onClick={handleRequestCreate}
          startIcon={creating ? <CircularProgress size={18} color="inherit" /> : undefined}
          sx={audiobookButtonSx.brandContained}
        >
          {creating ? t('audiobook.minimaxVoiceClone.creatingText') : t('audiobook.minimaxVoiceClone.createClone')}
        </Button>
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ minWidth: 240, flex: '1 1 280px', overflowWrap: 'anywhere' }}
        >
          {sampleSummary || t('audiobook.minimaxVoiceClone.noSampleYet')}
        </Typography>
      </Box>

      {createdPreview?.audioUrl && (
        <Box sx={{ mb: 1.25 }}>
          <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
            {t('audiobook.minimaxVoiceClone.previewTitle')}
          </Typography>
          <audio controls src={createdPreview.audioUrl} style={{ width: '100%', maxWidth: 560 }} />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            {t('audiobook.minimaxVoiceClone.voiceIdLabel', { voiceId: createdPreview.voiceId })}
          </Typography>
        </Box>
      )}
      {message && <Alert severity="success" sx={{ mb: 1 }}>{message}</Alert>}
      {error && <Alert severity="warning" sx={{ mb: 1 }}>{error}</Alert>}

      {minimaxPresets.length > 0 && (
        <>
          <Divider sx={{ my: 1.25 }} />
          <Typography variant="subtitle2" sx={{ mb: 0.75 }}>
            {t('audiobook.minimaxVoiceClone.currentModelClones')}
          </Typography>
          <Box sx={{ display: 'grid', gap: 0.75, maxHeight: 280, overflowY: 'auto' }}>
            {minimaxPresets.map((preset) => {
              const isPreviewing = previewingVoiceId === preset.id
              return (
                <Box
                  key={preset.id}
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: 'minmax(0, 1fr) auto',
                    gap: 1,
                    alignItems: 'center',
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 1,
                    p: 1,
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" sx={{ fontWeight: 700 }} noWrap>
                      {preset.label || preset.id}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
                      {preset.id}
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
                    <Chip label="MiniMax Clone" size="small" color="success" />
                    <Tooltip title={t('audiobook.minimaxVoiceClone.preview')}>
                      <span>
                        <IconButton
                          size="small"
                          disabled={Boolean(previewingVoiceId)}
                          onClick={() => onPreviewCustomVoice(preset, ttsModel)}
                          aria-label={t('audiobook.minimaxVoiceClone.previewAria', { name: preset.label || preset.id })}
                        >
                          {isPreviewing ? <CircularProgress size={18} /> : <PlayArrowIcon fontSize="small" />}
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title={t('audiobook.minimaxVoiceClone.removeFromList')}>
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => setRemoveTarget(preset)}
                        aria-label={t('audiobook.minimaxVoiceClone.removeAria', { name: preset.label || preset.id })}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                </Box>
              )
            })}
          </Box>
        </>
      )}

      <CosyVoiceCloneRecordDialog
        open={recordDialogOpen}
        cloneRecording={recording}
        cloneLoading={creating}
        cloneUploading={uploading}
        strictTranscriptMode
        transcriptText={sampleText.trim()}
        onClose={() => {
          if (!recording) setRecordDialogOpen(false)
        }}
        onStartCloneRecording={handleStartCloneRecording}
        onStopCloneRecording={handleStopCloneRecording}
      />

      <Dialog
        open={billingConfirmOpen}
        onClose={() => {
          if (!creating) setBillingConfirmOpen(false)
        }}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>{t('audiobook.minimaxVoiceClone.billingConfirmTitle')}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {t('audiobook.minimaxVoiceClone.billingConfirmBody', { previewPrice })}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {t('audiobook.minimaxVoiceClone.billingConfirmUnlock')}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            {t('audiobook.minimaxVoiceClone.billingSummary', { name: name.trim() || t('audiobook.minimaxVoiceClone.unnamed'), ttsModel })}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBillingConfirmOpen(false)} disabled={creating}>
            {t('action.cancel')}
          </Button>
          <Button
            variant="contained"
            color="warning"
            disabled={creating || !canCreate}
            onClick={handleConfirmCreate}
          >
            {creating ? t('audiobook.minimaxVoiceClone.creatingText') : t('audiobook.minimaxVoiceClone.confirmBillingCreate')}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={Boolean(removeTarget)}
        onClose={() => {
          if (!removing) setRemoveTarget(null)
        }}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>{t('audiobook.minimaxVoiceClone.removeLocalTitle')}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2">
            {t('audiobook.minimaxVoiceClone.removeLocalBody', { name: removeTarget?.label || removeTarget?.id })}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRemoveTarget(null)} disabled={removing}>{t('action.cancel')}</Button>
          <Button color="error" onClick={handleRemove} disabled={removing}>
            {removing ? t('audiobook.minimaxVoiceClone.removingText') : t('audiobook.minimaxVoiceClone.confirmRemove')}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  )
}

export default MiniMaxVoiceCloneWorkbench
