import { useMemo, useState, type ChangeEvent } from 'react'

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { useTranslation } from 'react-i18next'
import { audiobookButtonSx, audiobookColors } from './audiobookTheme'
import CosyVoiceCloneRecordDialog from './CosyVoiceCloneRecordDialog'
import type { TtsModel, VoicePreset } from './types'
import {
  convertRecordedAudioBlobToWavFile,
  isMimoCloneSupportedAudioFile,
  summarizeAudioFile,
} from './voiceCloneAudioUtils'
import { useCosyVoiceCloneRecording } from './useCosyVoiceCloneRecording'

interface StepAudioVoiceCloneWorkbenchProps {
  customVoicePresets: VoicePreset[]
  previewingVoiceId: string | null
  onPreviewCustomVoice: (voice: VoicePreset, model?: TtsModel) => void
  onChanged: () => void
}

interface StepAudioClonePreviewResult {
  fileId: string
  sampleText: string
  previewText: string
  instruction: string
  previewAudioUrl: string
  audioMimeType: string
  audioSizeBytes: number
}

const VISIBLE_STEPAUDIO_VOICE_LIMIT = 3

const extractStepAudioAssetId = (voiceId: string): string =>
  voiceId.replace(/^stepaudio_clone:/, '').trim()

const StepAudioVoiceCloneWorkbench = ({
  customVoicePresets,
  previewingVoiceId,
  onPreviewCustomVoice,
  onChanged,
}: StepAudioVoiceCloneWorkbenchProps) => {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [sampleText, setSampleText] = useState('')
  const [fileId, setFileId] = useState('')
  const [cloneSampleFile, setCloneSampleFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [previewResult, setPreviewResult] = useState<StepAudioClonePreviewResult | null>(null)
  const [uploading, setUploading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [recordDialogOpen, setRecordDialogOpen] = useState(false)
  const [billingConfirmOpen, setBillingConfirmOpen] = useState(false)
  const [showAllPresets, setShowAllPresets] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const filteredPresets = useMemo(
    () => customVoicePresets.filter((preset) => preset.id.startsWith('stepaudio_clone:')),
    [customVoicePresets],
  )
  const visiblePresets = showAllPresets
    ? filteredPresets
    : filteredPresets.slice(0, VISIBLE_STEPAUDIO_VOICE_LIMIT)
  const hiddenPresetCount = filteredPresets.length - visiblePresets.length

  const busy = loading || previewing || uploading || recording
  const cloneSampleSummary = cloneSampleFile ? summarizeAudioFile(cloneSampleFile) : ''
  const canPreview = Boolean(cloneSampleFile && sampleText.trim())
  const canSave = Boolean(name.trim() && cloneSampleFile && previewResult)

  const clearPreviewResult = () => {
    setPreviewResult(null)
  }

  const handleUploadAudio = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setUploading(true)
    setError(null)
    setMessage(null)
    try {
      if (!isMimoCloneSupportedAudioFile(file)) {
        throw new Error(t('audiobook.stepAudioWorkbench.sampleTypeError'))
      }
      setCloneSampleFile(file)
      clearPreviewResult()
      setMessage(t('audiobook.stepAudioWorkbench.sampleSelectedMessage'))
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.stepAudioWorkbench.selectSampleFailed')))
    } finally {
      setUploading(false)
    }
  }

  const uploadRecordedAudio = async (blob: Blob) => {
    setRecordDialogOpen(false)
    setUploading(true)
    setError(null)
    setMessage(null)
    try {
      const file = await convertRecordedAudioBlobToWavFile(blob)
      setCloneSampleFile(file)
      clearPreviewResult()
      setMessage(t('audiobook.stepAudioWorkbench.recordingConvertedMessage'))
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.stepAudioWorkbench.recordingConvertFailed')))
    } finally {
      setUploading(false)
    }
  }

  const {
    handleStartCloneRecording,
    handleStopCloneRecording,
  } = useCosyVoiceCloneRecording({
    cloneLoading: loading || previewing,
    cloneUploading: uploading,
    cloneRecording: recording,
    setCloneRecording: setRecording,
    onResetCloneMessages: () => {
      setError(null)
      setMessage(null)
    },
    onCloneError: setError,
    onUploadRecordedCloneAudio: uploadRecordedAudio,
  })

  const handleOpenRecordDialog = () => {
    setError(null)
    setMessage(null)
    if (!sampleText.trim()) {
      setError(t('audiobook.stepAudioWorkbench.transcriptRequiredForRecording'))
      return
    }
    setRecordDialogOpen(true)
  }

  const handlePreviewClone = async () => {
    setPreviewing(true)
    setError(null)
    setMessage(null)
    clearPreviewResult()
    try {
      if (!cloneSampleFile) {
        throw new Error(t('audiobook.stepAudioWorkbench.sampleRequired'))
      }
      if (!sampleText.trim()) {
        throw new Error(t('audiobook.stepAudioWorkbench.transcriptRequired'))
      }
      const response = await apiClient.previewStepAudioVoiceCloneAssetFromFile({
        name: name.trim(),
        file: cloneSampleFile,
        sampleText: sampleText.trim(),
        fileId: fileId.trim(),
      })
      const payload = response.data
      const audioMimeType = payload.audio_mime_type || 'audio/mpeg'
      const previewAudioUrl = `data:${audioMimeType};base64,${payload.audio_data_base64}`
      setFileId(payload.file_id || fileId.trim())
      setSampleText(payload.sample_text || sampleText.trim())
      setPreviewResult({
        fileId: payload.file_id || fileId.trim(),
        sampleText: payload.sample_text || sampleText.trim(),
        previewText: payload.preview_text || '',
        instruction: payload.instruction || '',
        previewAudioUrl,
        audioMimeType,
        audioSizeBytes: payload.audio_size_bytes || 0,
      })
      setMessage(t('audiobook.stepAudioWorkbench.previewGeneratedMessage'))
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.stepAudioWorkbench.previewFailed')))
    } finally {
      setPreviewing(false)
    }
  }

  const handleRequestConfirmSave = () => {
    setError(null)
    setMessage(null)
    if (!name.trim()) {
      setError(t('audiobook.stepAudioWorkbench.nameRequired'))
      return
    }
    if (!cloneSampleFile) {
      setError(t('audiobook.stepAudioWorkbench.sampleRequired'))
      return
    }
    if (!sampleText.trim()) {
      setError(t('audiobook.stepAudioWorkbench.transcriptRequired'))
      return
    }
    if (!previewResult) {
      setError(t('audiobook.stepAudioWorkbench.previewRequired'))
      return
    }
    setBillingConfirmOpen(true)
  }

  const handleCloseBillingConfirm = () => {
    if (loading) return
    setBillingConfirmOpen(false)
  }

  const handleConfirmSave = async () => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      if (!cloneSampleFile) {
        throw new Error(t('audiobook.stepAudioWorkbench.sampleRequired'))
      }
      if (!sampleText.trim()) {
        throw new Error(t('audiobook.stepAudioWorkbench.transcriptRequired'))
      }
      if (!previewResult) {
        throw new Error(t('audiobook.stepAudioWorkbench.previewRequired'))
      }
      await apiClient.createStepAudioVoiceCloneAssetFromFile({
        name: name.trim(),
        file: cloneSampleFile,
        sampleText: previewResult.sampleText,
        fileId: previewResult.fileId,
      })
      setName('')
      setSampleText('')
      setFileId('')
      setCloneSampleFile(null)
      clearPreviewResult()
      setMessage(t('audiobook.stepAudioWorkbench.savedMessage'))
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.stepAudioWorkbench.saveFailed')))
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmBillingSave = async () => {
    setBillingConfirmOpen(false)
    await handleConfirmSave()
  }

  const handleDelete = async (voiceId: string) => {
    const assetId = extractStepAudioAssetId(voiceId)
    setDeletingId(voiceId)
    setError(null)
    setMessage(null)
    try {
      await apiClient.deleteStepAudioVoiceAsset(assetId)
      setMessage(t('audiobook.stepAudioWorkbench.deletedMessage'))
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.stepAudioWorkbench.deleteFailed')))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Paper variant="outlined" sx={{ mb: 1, p: 1.5 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        {t('audiobook.stepAudioWorkbench.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {t('audiobook.stepAudioWorkbench.intro')}
      </Typography>

      <Paper
        variant="outlined"
        sx={{
          p: { xs: 1.5, md: 2 },
          display: 'grid',
          gap: 1.5,
          mb: 1.5,
        }}
      >
        <Box sx={{ minWidth: 0, maxWidth: 760 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1.25 }}>
            {t('audiobook.stepAudioWorkbench.referenceTitle')}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, lineHeight: 1.75 }}>
            {t('audiobook.stepAudioWorkbench.referenceExplain')}
          </Typography>
        </Box>

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) minmax(220px, 240px)' },
            gap: 1.25,
            alignItems: 'stretch',
            width: '100%',
            maxWidth: 760,
          }}
        >
          <TextField
            label={t('audiobook.stepAudioWorkbench.nameLabel')}
            value={name}
            onChange={(event) => setName(event.target.value)}
            size="small"
            fullWidth
            disabled={busy}
            sx={{ minWidth: 0 }}
          />
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0.75, minWidth: 0 }}>
            <Button
              fullWidth
              variant="outlined"
              disabled={busy || !canPreview}
              onClick={handlePreviewClone}
              startIcon={previewing ? <CircularProgress size={18} color="inherit" /> : undefined}
              sx={{ ...audiobookButtonSx.brandOutlined, minHeight: 40 }}
            >
              {previewing ? t('audiobook.stepAudioWorkbench.previewingText') : t('audiobook.stepAudioWorkbench.previewButton')}
            </Button>
            <Button
              fullWidth
              variant="contained"
              disabled={busy || !canSave}
              onClick={handleRequestConfirmSave}
              startIcon={loading ? <CircularProgress size={18} color="inherit" /> : undefined}
              sx={{ ...audiobookButtonSx.brandContained, minHeight: 40 }}
            >
              {loading ? t('audiobook.stepAudioWorkbench.savingText') : t('audiobook.stepAudioWorkbench.confirmSave')}
            </Button>
          </Box>
          <TextField
            label={t('audiobook.stepAudioWorkbench.transcriptLabel')}
            value={sampleText}
            onChange={(event) => {
              setSampleText(event.target.value)
              clearPreviewResult()
            }}
            size="small"
            fullWidth
            multiline
            minRows={3}
            maxRows={5}
            disabled={busy}
            placeholder={t('audiobook.stepAudioWorkbench.transcriptPlaceholder')}
            helperText={t('audiobook.stepAudioWorkbench.transcriptHelper')}
            sx={{ gridColumn: '1 / -1', minWidth: 0 }}
          />
          <TextField
            label={t('audiobook.stepAudioWorkbench.fileIdLabel')}
            value={fileId}
            onChange={(event) => {
              setFileId(event.target.value)
              clearPreviewResult()
            }}
            size="small"
            fullWidth
            disabled={busy}
            placeholder="file-Ckyl3cV09A"
            helperText={t('audiobook.stepAudioWorkbench.fileIdHelper')}
            sx={{ gridColumn: '1 / -1', minWidth: 0 }}
          />
          <Box
            sx={{
              gridColumn: '1 / -1',
              minWidth: 0,
              minHeight: 40,
              px: 1.5,
              py: 0.75,
              border: '1px solid',
              borderColor: cloneSampleFile ? 'success.main' : 'divider',
              borderRadius: 1,
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              backgroundColor: 'background.paper',
            }}
          >
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.2 }}>
                {cloneSampleFile ? t('audiobook.stepAudioWorkbench.sampleSelectedLabel') : t('audiobook.stepAudioWorkbench.sampleLabel')}
              </Typography>
              <Tooltip title={cloneSampleSummary || t('audiobook.stepAudioWorkbench.sampleRequired')}>
                <Typography
                  variant="body2"
                  sx={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {cloneSampleSummary || t('audiobook.stepAudioWorkbench.hasNoSample')}
                </Typography>
              </Tooltip>
            </Box>
            {cloneSampleFile && (
              <Button
                size="small"
                variant="text"
                disabled={busy}
                onClick={() => {
                  setCloneSampleFile(null)
                  clearPreviewResult()
                  setMessage(null)
                }}
                sx={{ minWidth: 64 }}
              >
                {t('audiobook.stepAudioWorkbench.clearSample')}
              </Button>
            )}
          </Box>
          {previewResult && (
            <Box
              sx={{
                gridColumn: '1 / -1',
                minWidth: 0,
                p: 1,
                border: '1px solid',
                borderColor: 'success.main',
                borderRadius: 1,
                backgroundColor: audiobookColors.successSoft,
              }}
            >
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
                {t('audiobook.stepAudioWorkbench.previewGeneratedWithFileId', { fileId: previewResult.fileId || t('audiobook.stepAudioWorkbench.notReturned') })}
              </Typography>
              <audio controls src={previewResult.previewAudioUrl} style={{ width: '100%', display: 'block' }} />
            </Box>
          )}
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <Button
            variant="outlined"
            disabled={busy}
            onClick={handleOpenRecordDialog}
            sx={audiobookButtonSx.neutralOutlined}
          >
            {t('audiobook.stepAudioWorkbench.record')}
          </Button>
          <Button
            variant="outlined"
            component="label"
            disabled={busy}
            startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : undefined}
            sx={audiobookButtonSx.brandOutlined}
          >
            {uploading ? t('audiobook.stepAudioWorkbench.uploadingText') : t('audiobook.stepAudioWorkbench.uploadAudio')}
            <input
              type="file"
              hidden
              accept=".mp3,.wav,audio/mpeg,audio/wav"
              onChange={handleUploadAudio}
            />
          </Button>
          <Typography variant="caption" color="text.secondary" sx={{ minWidth: 220, flex: '1 1 280px' }}>
            {t('audiobook.stepAudioWorkbench.formatHint')}
          </Typography>
        </Box>
      </Paper>

      {message && <Alert severity="success" sx={{ mb: 1 }}>{message}</Alert>}
      {error && <Alert severity="warning" sx={{ mb: 1 }}>{error}</Alert>}

      {filteredPresets.length > 0 && (
        <>
          <Divider sx={{ mb: 1 }} />
          <Box sx={{ display: 'grid', gap: 1 }}>
            {visiblePresets.map((preset) => {
              const isDeleting = deletingId === preset.id
              const isPreviewing = previewingVoiceId === preset.id
              const presetDisabled = Boolean(preset.disabled)
              const previewTooltip = presetDisabled
                ? (preset.disabledReason || t('audiobook.stepAudioWorkbench.previewDisabledTooltip'))
                : t('audiobook.stepAudioWorkbench.listen')
              return (
                <Box
                  key={preset.id}
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1fr) auto' },
                    gap: 1,
                    alignItems: 'center',
                    p: 1,
                    borderRadius: 1,
                    border: '1px solid',
                    borderColor: 'divider',
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography
                      variant="body2"
                      sx={{
                        fontWeight: 700,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {preset.label || preset.id}
                    </Typography>
                    <Tooltip title={preset.description || preset.id}>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{
                          display: 'block',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {preset.description || preset.id}
                      </Typography>
                    </Tooltip>
                    {preset.disabledReason && (
                      <Typography
                        variant="caption"
                        color="warning.main"
                        sx={{
                          display: 'block',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {preset.disabledReason}
                      </Typography>
                    )}
                  </Box>
                  <Box sx={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 0.5 }}>
                    <Chip label="Clone" size="small" color="success" />
                    <Tooltip title={previewTooltip}>
                      <span>
                        <IconButton
                          size="small"
                          disabled={presetDisabled || Boolean(previewingVoiceId) || isDeleting}
                          onClick={() => onPreviewCustomVoice(preset, 'stepaudio-2.5-tts')}
                          aria-label={t('audiobook.stepAudioWorkbench.previewAria', { label: preset.label || preset.id })}
                        >
                          {isPreviewing ? <CircularProgress size={18} /> : <PlayArrowIcon fontSize="small" />}
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title={isDeleting ? t('audiobook.stepAudioWorkbench.deleting') : t('audiobook.stepAudioWorkbench.delete')}>
                      <span>
                        <IconButton
                          size="small"
                          color="error"
                          disabled={isDeleting}
                          onClick={() => handleDelete(preset.id)}
                          aria-label={t('audiobook.stepAudioWorkbench.deleteAria', { label: preset.label || preset.id })}
                        >
                          {isDeleting ? <CircularProgress size={18} /> : <DeleteOutlineIcon fontSize="small" />}
                        </IconButton>
                      </span>
                    </Tooltip>
                  </Box>
                </Box>
              )
            })}
            {filteredPresets.length > VISIBLE_STEPAUDIO_VOICE_LIMIT && (
              <Button
                size="small"
                variant="text"
                endIcon={showAllPresets ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                onClick={() => setShowAllPresets((current) => !current)}
                sx={{ justifySelf: 'start', fontSize: '0.75rem', minWidth: 0 }}
              >
                {showAllPresets ? t('audiobook.stepAudioWorkbench.collapse') : t('audiobook.stepAudioWorkbench.expandCount', { count: hiddenPresetCount })}
              </Button>
            )}
          </Box>
        </>
      )}
      <CosyVoiceCloneRecordDialog
        open={recordDialogOpen}
        cloneRecording={recording}
        cloneLoading={loading}
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
        onClose={handleCloseBillingConfirm}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>{t('audiobook.stepAudioWorkbench.billingTitle')}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {t('audiobook.stepAudioWorkbench.billingBody1')}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {t('audiobook.stepAudioWorkbench.billingBody2')}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            {t('audiobook.stepAudioWorkbench.billingSummary', { name: name.trim() || t('audiobook.stepAudioWorkbench.unnamed'), fileId: previewResult?.fileId || t('audiobook.stepAudioWorkbench.notReturned') })}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseBillingConfirm} disabled={loading}>
            {t('action.cancel')}
          </Button>
          <Button
            variant="contained"
            color="warning"
            disabled={loading || !canSave}
            onClick={handleConfirmBillingSave}
            startIcon={loading ? <CircularProgress size={18} color="inherit" /> : undefined}
          >
            {loading ? t('audiobook.stepAudioWorkbench.savingText') : t('audiobook.stepAudioWorkbench.confirmBillingSave')}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  )
}

export default StepAudioVoiceCloneWorkbench
