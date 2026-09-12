import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import UploadFileIcon from '@mui/icons-material/UploadFile'

import { apiClient } from '../../services/api'

type AudioLibraryType = 'sfx' | 'music'

interface AudioLibraryUploadDialogProps {
  open: boolean
  initialLibraryType: AudioLibraryType
  onClose: () => void
  onUploaded: (libraryType: AudioLibraryType) => void
}

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

const AudioLibraryUploadDialog = ({
  open,
  initialLibraryType,
  onClose,
  onUploaded,
}: AudioLibraryUploadDialogProps) => {
  const { t } = useTranslation()
  const [libraryType, setLibraryType] = useState<AudioLibraryType>(initialLibraryType)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('environment/realistic')
  const [style, setStyle] = useState('')
  const [mood, setMood] = useState('')
  const [tags, setTags] = useState('')
  const [licenseCommercial, setLicenseCommercial] = useState(false)
  const [rightsConfirmed, setRightsConfirmed] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setLibraryType(initialLibraryType)
    setName('')
    setDescription('')
    setCategory('environment/realistic')
    setStyle('')
    setMood('')
    setTags('')
    setLicenseCommercial(false)
    setRightsConfirmed(false)
    setFile(null)
    setSubmitting(false)
    setError('')
  }, [initialLibraryType, open])

  const handleSubmit = async () => {
    const normalizedName = name.trim()
    if (!normalizedName || !/[\u4e00-\u9fff]/.test(normalizedName)) {
      setError(t('audiobook.audioLibraryUpload.chineseNameRequired'))
      return
    }
    if (!file) {
      setError(t('audiobook.audioLibraryUpload.fileRequired'))
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError(t('audiobook.audioLibraryUpload.fileTooLarge'))
      return
    }
    if (!rightsConfirmed) {
      setError(t('audiobook.audioLibraryUpload.rightsNotConfirmed'))
      return
    }

    const payload = new FormData()
    payload.append('library_type', libraryType)
    payload.append('name', normalizedName)
    payload.append('description', description.trim())
    payload.append('category', libraryType === 'sfx' ? category : '')
    payload.append('style', style.trim())
    payload.append('mood', mood.trim())
    payload.append('tags', tags.trim())
    payload.append('license_commercial', String(licenseCommercial))
    payload.append('rights_confirmed', String(rightsConfirmed))
    payload.append('file', file)

    setSubmitting(true)
    setError('')
    try {
      await apiClient.uploadAudioLibraryAsset(payload)
      onUploaded(libraryType)
      onClose()
    } catch (requestError: unknown) {
      const detail = (requestError as { response?: { data?: { detail?: string } } })
        .response?.data?.detail
      setError(detail || t('audiobook.audioLibraryUpload.uploadFailed'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onClose={submitting ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('audiobook.audioLibraryUpload.title')}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}

          <ToggleButtonGroup
            exclusive
            fullWidth
            size="small"
            value={libraryType}
            onChange={(_, value: AudioLibraryType | null) => {
              if (value) setLibraryType(value)
            }}
          >
            <ToggleButton value="sfx">{t('audiobook.audioLibraryUpload.sfxTab')}</ToggleButton>
            <ToggleButton value="music">{t('audiobook.audioLibraryUpload.musicTab')}</ToggleButton>
          </ToggleButtonGroup>

          <TextField
            required
            label={t('audiobook.audioLibraryUpload.nameLabel')}
            value={name}
            onChange={(event) => setName(event.target.value)}
            inputProps={{ maxLength: 100 }}
          />
          <TextField
            label={t('audiobook.audioLibraryUpload.descriptionLabel')}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            multiline
            minRows={2}
          />

          {libraryType === 'sfx' ? (
            <FormControl fullWidth>
              <InputLabel>{t('audiobook.audioLibraryUpload.sfxCategoryLabel')}</InputLabel>
              <Select
                label={t('audiobook.audioLibraryUpload.sfxCategoryLabel')}
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                <MenuItem value="environment/realistic">{t('audiobook.audioLibraryUpload.categoryEnvRealistic')}</MenuItem>
                <MenuItem value="action/realistic">{t('audiobook.audioLibraryUpload.categoryActionRealistic')}</MenuItem>
                <MenuItem value="emotion/realistic">{t('audiobook.audioLibraryUpload.categoryEmotionRealistic')}</MenuItem>
                <MenuItem value="transition/cinematic">{t('audiobook.audioLibraryUpload.categoryTransitionCinematic')}</MenuItem>
                <MenuItem value="environment/fantasy">{t('audiobook.audioLibraryUpload.categoryEnvFantasy')}</MenuItem>
                <MenuItem value="action/scifi">{t('audiobook.audioLibraryUpload.categoryActionScifi')}</MenuItem>
              </Select>
            </FormControl>
          ) : (
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1.5 }}>
              <TextField
                label={t('audiobook.audioLibraryUpload.musicStyleLabel')}
                value={style}
                onChange={(event) => setStyle(event.target.value)}
              />
              <TextField
                label={t('audiobook.audioLibraryUpload.musicMoodLabel')}
                value={mood}
                onChange={(event) => setMood(event.target.value)}
              />
            </Box>
          )}

          <TextField
            label={t('audiobook.audioLibraryUpload.tagsLabel')}
            value={tags}
            onChange={(event) => setTags(event.target.value)}
            placeholder={t('audiobook.audioLibraryUpload.tagsPlaceholder')}
          />

          <Button
            component="label"
            variant="outlined"
            startIcon={<UploadFileIcon />}
            disabled={submitting}
            sx={{ justifyContent: 'flex-start', minHeight: 44 }}
          >
            {file ? file.name : t('audiobook.audioLibraryUpload.chooseFile')}
            <input
              hidden
              type="file"
              accept="audio/mpeg,audio/wav,audio/ogg,audio/flac,audio/mp4,.mp3,.wav,.ogg,.flac,.m4a"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </Button>
          {file && (
            <Typography variant="caption" color="text.secondary">
              {(file.size / 1024 / 1024).toFixed(2)} MB
            </Typography>
          )}

          <FormControlLabel
            control={(
              <Checkbox
                checked={licenseCommercial}
                onChange={(event) => setLicenseCommercial(event.target.checked)}
              />
            )}
            label={t('audiobook.audioLibraryUpload.commercialLabel')}
          />
          <FormControlLabel
            control={(
              <Checkbox
                checked={rightsConfirmed}
                onChange={(event) => setRightsConfirmed(event.target.checked)}
              />
            )}
            label={t('audiobook.audioLibraryUpload.rightsLabel')}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>{t('action.cancel')}</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={submitting || !file || !rightsConfirmed}
          startIcon={submitting ? undefined : <UploadFileIcon />}
        >
          {submitting
            ? t('audiobook.mimoVoiceAssetWorkbench.uploadingText')
            : t('audiobook.audioLibraryUpload.uploadAssetText')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default AudioLibraryUploadDialog
