import { useEffect, useState } from 'react'
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
      setError('请输入中文素材名称')
      return
    }
    if (!file) {
      setError('请选择音频文件')
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError('音频文件不能超过 50MB')
      return
    }
    if (!rightsConfirmed) {
      setError('请确认拥有该音频的共享和使用授权')
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
      setError(detail || '上传失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onClose={submitting ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>上传共享音频素材</DialogTitle>
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
            <ToggleButton value="sfx">音效</ToggleButton>
            <ToggleButton value="music">配乐</ToggleButton>
          </ToggleButtonGroup>

          <TextField
            required
            label="中文素材名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
            inputProps={{ maxLength: 100 }}
          />
          <TextField
            label="素材描述"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            multiline
            minRows={2}
          />

          {libraryType === 'sfx' ? (
            <FormControl fullWidth>
              <InputLabel>音效分类</InputLabel>
              <Select
                label="音效分类"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                <MenuItem value="environment/realistic">环境 · 写实</MenuItem>
                <MenuItem value="action/realistic">动作 · 写实</MenuItem>
                <MenuItem value="emotion/realistic">情绪 · 写实</MenuItem>
                <MenuItem value="transition/cinematic">转场 · 电影感</MenuItem>
                <MenuItem value="environment/fantasy">环境 · 奇幻</MenuItem>
                <MenuItem value="action/scifi">动作 · 科幻</MenuItem>
              </Select>
            </FormControl>
          ) : (
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1.5 }}>
              <TextField
                label="配乐风格"
                value={style}
                onChange={(event) => setStyle(event.target.value)}
              />
              <TextField
                label="配乐情绪"
                value={mood}
                onChange={(event) => setMood(event.target.value)}
              />
            </Box>
          )}

          <TextField
            label="标签"
            value={tags}
            onChange={(event) => setTags(event.target.value)}
            placeholder="雨声，室内，轻柔"
          />

          <Button
            component="label"
            variant="outlined"
            startIcon={<UploadFileIcon />}
            disabled={submitting}
            sx={{ justifyContent: 'flex-start', minHeight: 44 }}
          >
            {file ? file.name : '选择音频文件'}
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
            label="允许后续使用者用于商业项目"
          />
          <FormControlLabel
            control={(
              <Checkbox
                checked={rightsConfirmed}
                onChange={(event) => setRightsConfirmed(event.target.checked)}
              />
            )}
            label="我确认拥有该音频的共享和使用授权"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>取消</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={submitting || !file || !rightsConfirmed}
          startIcon={submitting ? undefined : <UploadFileIcon />}
        >
          {submitting ? '上传中...' : '上传素材'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default AudioLibraryUploadDialog
