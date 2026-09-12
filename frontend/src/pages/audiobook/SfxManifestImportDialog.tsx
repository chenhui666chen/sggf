import { useEffect, useState } from 'react'
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
  FormControlLabel,
  IconButton,
  TextField,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import { useTranslation } from 'react-i18next'

import { apiClient } from '../../services/api'

interface SfxManifestImportDialogProps {
  open: boolean
  onClose: () => void
  onImported?: () => void
}

interface ImportStats {
  candidates: number
  imported: number
  rejected_license: number
  rejected_file: number
  rejected_quality: number
  skipped_existing: number
}

const EMPTY_STATS: ImportStats = {
  candidates: 0,
  imported: 0,
  rejected_license: 0,
  rejected_file: 0,
  rejected_quality: 0,
  skipped_existing: 0,
}

const SfxManifestImportDialog = ({ open, onClose, onImported }: SfxManifestImportDialogProps) => {
  const { t } = useTranslation()
  const [manifestPath, setManifestPath] = useState('sfx_import_manifest_draft.jsonl')
  const [sourceDir, setSourceDir] = useState('approved_sfx')
  const [overwrite, setOverwrite] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [checking, setChecking] = useState(false)
  const [importing, setImporting] = useState(false)
  const [stats, setStats] = useState<ImportStats | null>(null)
  const [recordCount, setRecordCount] = useState(0)
  const [previewRequestKey, setPreviewRequestKey] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const currentRequestKey = JSON.stringify([
    manifestPath.trim(),
    sourceDir.trim(),
    overwrite,
  ])
  const previewIsCurrent = previewRequestKey === currentRequestKey
  const canImport = Boolean(stats && recordCount > 0 && confirmed && previewIsCurrent)

  useEffect(() => {
    setStats(null)
    setRecordCount(0)
    setPreviewRequestKey(null)
    setConfirmed(false)
    setMessage('')
    setError('')
  }, [currentRequestKey])

  const runImport = async (dryRun: boolean) => {
    if (!dryRun && !canImport) {
      setError(t('audiobook.sfxManifestImport.staleConditionError'))
      return
    }
    if (dryRun) {
      setChecking(true)
    } else {
      setImporting(true)
    }
    setError('')
    setMessage('')
    try {
      const res = await apiClient.importSfxManifest({
        manifest_path: manifestPath,
        source_dir: sourceDir,
        dry_run: dryRun,
        confirm: !dryRun && confirmed,
        overwrite,
      })
      setStats(res.data.stats || EMPTY_STATS)
      setRecordCount(res.data.records.length)
      if (dryRun) {
        setPreviewRequestKey(currentRequestKey)
        setConfirmed(false)
        setMessage(t('audiobook.sfxManifestImport.precheckDone', {
          candidates: res.data.stats.candidates,
          importable: res.data.records.length,
        }))
      } else {
        setPreviewRequestKey(null)
        setConfirmed(false)
        setMessage(t('audiobook.sfxManifestImport.importDone', { total: res.data.stats.imported }))
        onImported?.()
      }
    } catch {
      setError(dryRun
        ? t('audiobook.sfxManifestImport.precheckFailed')
        : t('audiobook.sfxManifestImport.importFailed'))
    } finally {
      setChecking(false)
      setImporting(false)
    }
  }

  const handleClose = () => {
    setMessage('')
    setError('')
    setStats(null)
    setRecordCount(0)
    setPreviewRequestKey(null)
    setConfirmed(false)
    onClose()
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        {t('audiobook.sfxManifestImport.title')}
        <IconButton onClick={handleClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Alert severity="info" sx={{ mb: 2 }}>
          {t('audiobook.sfxManifestImport.infoHint')}
        </Alert>

        <Box sx={{ display: 'grid', gap: 1.5 }}>
          <TextField
            size="small"
            label={t('audiobook.sfxManifestImport.manifestPathLabel')}
            value={manifestPath}
            onChange={(event) => setManifestPath(event.target.value)}
            disabled={checking || importing}
            helperText={t('audiobook.sfxManifestImport.manifestPathHelper')}
          />
          <TextField
            size="small"
            label={t('audiobook.sfxCandidateReview.sourceDirLabel')}
            value={sourceDir}
            onChange={(event) => setSourceDir(event.target.value)}
            disabled={checking || importing}
            helperText={t('audiobook.sfxManifestImport.sourceDirHelper')}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={overwrite}
                onChange={(event) => setOverwrite(event.target.checked)}
                disabled={checking || importing}
              />
            }
            label={t('audiobook.sfxManifestImport.overwriteLabel')}
          />
        </Box>

        {stats && (
          <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 2 }}>
            <Chip label={t('audiobook.sfxManifestImport.candidateChip', { total: stats.candidates })} size="small" />
            <Chip label={t('audiobook.sfxManifestImport.importableChip', { total: recordCount })} size="small" color="success" />
            <Chip label={t('audiobook.sfxManifestImport.importedChip', { total: stats.imported })} size="small" color="success" variant="outlined" />
            <Chip label={t('audiobook.sfxManifestImport.licenseRejectedChip', { total: stats.rejected_license })} size="small" />
            <Chip label={t('audiobook.sfxManifestImport.fileRejectedChip', { total: stats.rejected_file })} size="small" />
            <Chip label={t('audiobook.sfxManifestImport.qualityRejectedChip', { total: stats.rejected_quality })} size="small" />
            <Chip label={t('audiobook.sfxManifestImport.existingChip', { total: stats.skipped_existing })} size="small" />
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
              disabled={!stats || stats.candidates === 0 || !previewIsCurrent || checking || importing}
            />
          }
          label={t('audiobook.sfxManifestImport.confirmLabel')}
        />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {t('audiobook.sfxManifestImport.indexHint')}
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('action.close')}</Button>
        <Button
          variant="outlined"
          onClick={() => runImport(true)}
          disabled={checking || importing}
        >
          {checking ? t('audiobook.sfxManifestImport.checkingText') : t('audiobook.sfxManifestImport.dryRunPrecheck')}
        </Button>
        <Button
          variant="contained"
          startIcon={importing ? <CircularProgress size={16} color="inherit" /> : <UploadFileIcon />}
          onClick={() => runImport(false)}
          disabled={checking || importing || !canImport}
        >
          {t('audiobook.sfxManifestImport.executeImport')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default SfxManifestImportDialog
