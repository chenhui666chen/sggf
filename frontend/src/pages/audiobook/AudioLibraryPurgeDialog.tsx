import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import CleanIcon from '@mui/icons-material/CleaningServices'
import CloseIcon from '@mui/icons-material/Close'

import { apiClient } from '../../services/api'

type LibraryType = 'sfx' | 'music' | 'both'

interface CleanupDetail {
  library_type: string
  id: string
  name: string
  file_path: string
  reason: string
  size: number
}

interface CleanupResult {
  stats: {
    removed_orphaned: number
    removed_missing: number
    removed_low_quality: number
    freed_bytes: number
  }
  details: {
    missing_entries: CleanupDetail[]
    low_quality_entries: CleanupDetail[]
    orphaned_files: CleanupDetail[]
  }
}

interface AudioLibraryPurgeDialogProps {
  open: boolean
  initialLibraryType?: LibraryType
  onClose: () => void
  onPurged?: () => void
}

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const AudioLibraryPurgeDialog = ({
  open,
  initialLibraryType = 'sfx',
  onClose,
  onPurged,
}: AudioLibraryPurgeDialogProps) => {
  const { t } = useTranslation()
  const [libraryType, setLibraryType] = useState<LibraryType>(initialLibraryType)
  const [removeMissing, setRemoveMissing] = useState(true)
  const [removeOrphaned, setRemoveOrphaned] = useState(true)
  const [removeLowQuality, setRemoveLowQuality] = useState(false)
  const [minQualityScore, setMinQualityScore] = useState(40)
  const [confirmed, setConfirmed] = useState(false)
  const [checking, setChecking] = useState(false)
  const [purging, setPurging] = useState(false)
  const [result, setResult] = useState<CleanupResult | null>(null)
  const [previewRequestKey, setPreviewRequestKey] = useState<string | null>(null)
  const [previewPlanToken, setPreviewPlanToken] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const currentRequestKey = JSON.stringify([
    libraryType,
    removeMissing,
    removeOrphaned,
    removeLowQuality,
    minQualityScore,
  ])
  const previewIsCurrent = previewRequestKey === currentRequestKey
    && result !== null
    && Boolean(previewPlanToken)
  const totalAffected = previewIsCurrent && result
    ? result.stats.removed_missing + result.stats.removed_orphaned + result.stats.removed_low_quality
    : 0

  useEffect(() => {
    if (open) setLibraryType(initialLibraryType)
  }, [initialLibraryType, open])

  useEffect(() => {
    setResult(null)
    setPreviewRequestKey(null)
    setPreviewPlanToken('')
    setConfirmed(false)
    setMessage('')
    setError('')
  }, [currentRequestKey])

  const runCleanup = async (dryRun: boolean) => {
    if (!dryRun && (!previewIsCurrent || !confirmed)) {
      setError(t('audiobook.audioLibraryPurge.staleConditionError'))
      return
    }
    if (dryRun) setChecking(true)
    else setPurging(true)
    setMessage('')
    setError('')
    try {
      const res = await apiClient.cleanupAudioLibrary({
        library_type: libraryType,
        remove_missing_files: removeMissing,
        remove_orphaned: removeOrphaned,
        remove_low_quality: removeLowQuality,
        min_quality_score: minQualityScore,
        dry_run: dryRun,
        confirm: !dryRun && confirmed,
        plan_token: previewPlanToken,
      })
      setResult({ stats: res.data.stats, details: res.data.details })
      if (dryRun) {
        const affected = res.data.stats.removed_missing
          + res.data.stats.removed_orphaned
          + res.data.stats.removed_low_quality
        setPreviewRequestKey(currentRequestKey)
        setPreviewPlanToken(res.data.plan_token)
        setConfirmed(false)
        setMessage(t('audiobook.audioLibraryPurge.dryRunDone', {
          total: affected,
        }))
      } else {
        setPreviewRequestKey(null)
        setPreviewPlanToken('')
        setConfirmed(false)
        setMessage(t('audiobook.audioLibraryPurge.purgeDone'))
        onPurged?.()
      }
    } catch {
      setError(dryRun
        ? t('audiobook.audioLibraryPurge.previewFailed')
        : t('audiobook.audioLibraryPurge.purgeFailed'))
    } finally {
      setChecking(false)
      setPurging(false)
    }
  }

  const handleClose = () => {
    setMessage('')
    setError('')
    setResult(null)
    setPreviewRequestKey(null)
    setPreviewPlanToken('')
    setConfirmed(false)
    onClose()
  }

  const renderDetails = (title: string, items: CleanupDetail[]) => {
    if (items.length === 0) return null
    return (
      <Box sx={{ mt: 2 }}>
        <Typography variant="subtitle2">{title}</Typography>
        <List dense disablePadding sx={{ maxHeight: 160, overflow: 'auto', border: '1px solid', borderColor: 'divider', mt: 1 }}>
          {items.map((item, index) => (
            <ListItem key={`${item.reason}-${item.file_path}-${index}`} sx={{ py: 0.75 }}>
              <ListItemText
                primary={item.name || item.id || item.file_path}
                secondary={item.file_path}
              />
              <Chip label={item.library_type} size="small" variant="outlined" sx={{ mr: 1 }} />
              <Typography variant="caption" color="text.secondary">
                {formatBytes(item.size)}
              </Typography>
            </ListItem>
          ))}
        </List>
      </Box>
    )
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        {t('audiobook.audioLibraryPurge.title')}
        <IconButton onClick={handleClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t('audiobook.audioLibraryPurge.warningHint')}
        </Alert>

        <Box sx={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 1.5, alignItems: 'center' }}>
          <FormControl size="small" disabled={checking || purging}>
            <InputLabel>{t('audiobook.audioLibraryPurge.libraryTypeLabel')}</InputLabel>
            <Select
              label={t('audiobook.audioLibraryPurge.libraryTypeLabel')}
              value={libraryType}
              onChange={(event) => setLibraryType(event.target.value as LibraryType)}
            >
              <MenuItem value="sfx">{t('audiobook.audioLibraryPurge.sfxLibrary')}</MenuItem>
              <MenuItem value="music">{t('audiobook.audioLibraryPurge.musicLibrary')}</MenuItem>
              <MenuItem value="both">{t('audiobook.audioLibraryPurge.bothLibraries')}</MenuItem>
            </Select>
          </FormControl>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            <FormControlLabel
              control={<Checkbox checked={removeMissing} onChange={(event) => setRemoveMissing(event.target.checked)} disabled={checking || purging} />}
              label={t('audiobook.audioLibraryPurge.missingLabel')}
            />
            <FormControlLabel
              control={<Checkbox checked={removeOrphaned} onChange={(event) => setRemoveOrphaned(event.target.checked)} disabled={checking || purging} />}
              label={t('audiobook.audioLibraryPurge.orphanedLabel')}
            />
            <FormControlLabel
              control={<Checkbox checked={removeLowQuality} onChange={(event) => setRemoveLowQuality(event.target.checked)} disabled={checking || purging} />}
              label={t('audiobook.audioLibraryPurge.lowQualityLabel')}
            />
          </Box>
          <TextField
            size="small"
            label={t('audiobook.audioLibraryPurge.minQualityLabel')}
            type="number"
            value={minQualityScore}
            onChange={(event) => setMinQualityScore(Number(event.target.value) || 0)}
            disabled={!removeLowQuality || checking || purging}
          />
          <Typography variant="caption" color="text.secondary">
            {t('audiobook.audioLibraryPurge.minQualityHint')}
          </Typography>
        </Box>

        {result && (
          <Box sx={{ mt: 2 }}>
            <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
              <Chip label={t('audiobook.audioLibraryPurge.missingCount', {
                total: result.stats.removed_missing,
              })} size="small" />
              <Chip label={t('audiobook.audioLibraryPurge.orphanedCount', {
                total: result.stats.removed_orphaned,
              })} size="small" />
              <Chip label={t('audiobook.audioLibraryPurge.lowQualityCount', {
                total: result.stats.removed_low_quality,
              })} size="small" />
              <Chip label={t('audiobook.audioLibraryPurge.freedBytes', {
                size: formatBytes(result.stats.freed_bytes),
              })} size="small" />
            </Box>
            {renderDetails(t('audiobook.audioLibraryPurge.missingLabel'), result.details.missing_entries)}
            {renderDetails(t('audiobook.audioLibraryPurge.lowQualityLabel'), result.details.low_quality_entries)}
            {renderDetails(t('audiobook.audioLibraryPurge.orphanedLabel'), result.details.orphaned_files)}
          </Box>
        )}

        {message && <Alert severity="success" sx={{ mt: 2 }}>{message}</Alert>}
        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}

        <FormControlLabel
          sx={{ mt: 2 }}
          control={
            <Checkbox
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              disabled={!previewIsCurrent || totalAffected === 0 || checking || purging}
            />
          }
          label={t('audiobook.audioLibraryPurge.confirmLabel')}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('action.close')}</Button>
        <Button
          variant="outlined"
          onClick={() => runCleanup(true)}
          disabled={checking || purging}
        >
          {checking
            ? t('audiobook.audioLibraryPurge.previewingText')
            : t('audiobook.audioLibraryPurge.dryRunPreview')}
        </Button>
        <Button
          variant="contained"
          color="warning"
          startIcon={purging ? <CircularProgress size={16} color="inherit" /> : <CleanIcon />}
          onClick={() => runCleanup(false)}
          disabled={checking || purging || !confirmed || totalAffected === 0}
        >
          {t('audiobook.audioLibraryPurge.executePurge')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default AudioLibraryPurgeDialog
