import { useState } from 'react'
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
  const [manifestPath, setManifestPath] = useState('sfx_import_manifest_draft.jsonl')
  const [sourceDir, setSourceDir] = useState('approved_sfx')
  const [overwrite, setOverwrite] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [checking, setChecking] = useState(false)
  const [importing, setImporting] = useState(false)
  const [stats, setStats] = useState<ImportStats | null>(null)
  const [recordCount, setRecordCount] = useState(0)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const canImport = Boolean(stats && recordCount > 0 && confirmed)

  const runImport = async (dryRun: boolean) => {
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
        setMessage(`预检完成：候选 ${res.data.stats.candidates} 个，可导入 ${res.data.records.length} 个。`)
      } else {
        setMessage(`manifest 导入完成：已导入 ${res.data.stats.imported} 个音效。`)
        onImported?.()
      }
    } catch {
      setError(dryRun ? 'manifest 预检失败，请检查路径和授权元数据' : 'manifest 导入失败，请先完成预检并确认导入')
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
    setConfirmed(false)
    onClose()
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        manifest 导入
        <IconButton onClick={handleClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Alert severity="info" sx={{ mb: 2 }}>
          仅导入本地已授权素材。请先 dry_run 预检，确认许可、来源和文件均通过后再执行实际导入。
        </Alert>

        <Box sx={{ display: 'grid', gap: 1.5 }}>
          <TextField
            size="small"
            label="manifest 路径"
            value={manifestPath}
            onChange={(event) => {
              setManifestPath(event.target.value)
              setStats(null)
              setConfirmed(false)
            }}
            helperText="必须位于音频素材库目录内"
          />
          <TextField
            size="small"
            label="本地素材目录"
            value={sourceDir}
            onChange={(event) => {
              setSourceDir(event.target.value)
              setStats(null)
              setConfirmed(false)
            }}
            helperText="manifest 中的 file 字段会按该目录解析"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={overwrite}
                onChange={(event) => setOverwrite(event.target.checked)}
              />
            }
            label="允许覆盖已存在文件"
          />
        </Box>

        {stats && (
          <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 2 }}>
            <Chip label={`候选 ${stats.candidates}`} size="small" />
            <Chip label={`可导入 ${recordCount}`} size="small" color="success" />
            <Chip label={`已导入 ${stats.imported}`} size="small" color="success" variant="outlined" />
            <Chip label={`许可拒绝 ${stats.rejected_license}`} size="small" />
            <Chip label={`文件拒绝 ${stats.rejected_file}`} size="small" />
            <Chip label={`质量拒绝 ${stats.rejected_quality}`} size="small" />
            <Chip label={`已存在 ${stats.skipped_existing}`} size="small" />
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
              disabled={!stats || stats.candidates === 0}
            />
          }
          label="我确认这些素材已获得商用授权，并同意写入本地音效库索引"
        />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          实际导入会复制本地文件并写入 `sound_effects_index.json`。
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>关闭</Button>
        <Button
          variant="outlined"
          onClick={() => runImport(true)}
          disabled={checking || importing}
        >
          {checking ? '预检中...' : 'dry_run 预检'}
        </Button>
        <Button
          variant="contained"
          startIcon={importing ? <CircularProgress size={16} color="inherit" /> : <UploadFileIcon />}
          onClick={() => runImport(false)}
          disabled={checking || importing || !canImport}
        >
          执行导入
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default SfxManifestImportDialog
