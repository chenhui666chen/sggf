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
  const [libraryType, setLibraryType] = useState<LibraryType>(initialLibraryType)
  const [removeMissing, setRemoveMissing] = useState(true)
  const [removeOrphaned, setRemoveOrphaned] = useState(true)
  const [removeLowQuality, setRemoveLowQuality] = useState(false)
  const [minQualityScore, setMinQualityScore] = useState(40)
  const [confirmed, setConfirmed] = useState(false)
  const [checking, setChecking] = useState(false)
  const [purging, setPurging] = useState(false)
  const [result, setResult] = useState<CleanupResult | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const totalAffected = result
    ? result.stats.removed_missing + result.stats.removed_orphaned + result.stats.removed_low_quality
    : 0

  const runCleanup = async (dryRun: boolean) => {
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
      })
      setResult({ stats: res.data.stats, details: res.data.details })
      if (dryRun) {
        setMessage(`dry_run 完成：发现 ${totalAffected || (
          res.data.stats.removed_missing + res.data.stats.removed_orphaned + res.data.stats.removed_low_quality
        )} 项可清理。`)
      } else {
        setMessage('素材清理完成')
        onPurged?.()
      }
    } catch {
      setError(dryRun ? '清理预览失败' : '执行清理失败，请先 dry_run 并勾选确认')
    } finally {
      setChecking(false)
      setPurging(false)
    }
  }

  const handleClose = () => {
    setMessage('')
    setError('')
    setResult(null)
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
        素材清理
        <IconButton onClick={handleClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Alert severity="warning" sx={{ mb: 2 }}>
          清理必须先 dry_run 预览。实际执行会改写索引，并删除素材库目录内的孤立或低质文件。
        </Alert>

        <Box sx={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 1.5, alignItems: 'center' }}>
          <FormControl size="small">
            <InputLabel>库类型</InputLabel>
            <Select
              label="库类型"
              value={libraryType}
              onChange={(event) => setLibraryType(event.target.value as LibraryType)}
            >
              <MenuItem value="sfx">音效库</MenuItem>
              <MenuItem value="music">音乐库</MenuItem>
              <MenuItem value="both">全部</MenuItem>
            </Select>
          </FormControl>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            <FormControlLabel
              control={<Checkbox checked={removeMissing} onChange={(event) => setRemoveMissing(event.target.checked)} />}
              label="缺失索引"
            />
            <FormControlLabel
              control={<Checkbox checked={removeOrphaned} onChange={(event) => setRemoveOrphaned(event.target.checked)} />}
              label="孤立文件"
            />
            <FormControlLabel
              control={<Checkbox checked={removeLowQuality} onChange={(event) => setRemoveLowQuality(event.target.checked)} />}
              label="低质素材"
            />
          </Box>
          <TextField
            size="small"
            label="最低质量分"
            type="number"
            value={minQualityScore}
            onChange={(event) => setMinQualityScore(Number(event.target.value) || 0)}
            disabled={!removeLowQuality}
          />
          <Typography variant="caption" color="text.secondary">
            低于该分数或 `quality_status=rejected` 的素材会进入低质清理预览。
          </Typography>
        </Box>

        {result && (
          <Box sx={{ mt: 2 }}>
            <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
              <Chip label={`缺失索引 ${result.stats.removed_missing}`} size="small" />
              <Chip label={`孤立文件 ${result.stats.removed_orphaned}`} size="small" />
              <Chip label={`低质素材 ${result.stats.removed_low_quality}`} size="small" />
              <Chip label={`可释放 ${formatBytes(result.stats.freed_bytes)}`} size="small" />
            </Box>
            {renderDetails('缺失索引', result.details.missing_entries)}
            {renderDetails('低质素材', result.details.low_quality_entries)}
            {renderDetails('孤立文件', result.details.orphaned_files)}
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
              disabled={!result || totalAffected === 0}
            />
          }
          label="我确认执行上述清理并允许写入索引"
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>关闭</Button>
        <Button
          variant="outlined"
          onClick={() => runCleanup(true)}
          disabled={checking || purging}
        >
          {checking ? '预览中...' : 'dry_run 预览'}
        </Button>
        <Button
          variant="contained"
          color="warning"
          startIcon={purging ? <CircularProgress size={16} color="inherit" /> : <CleanIcon />}
          onClick={() => runCleanup(false)}
          disabled={checking || purging || !confirmed || totalAffected === 0}
        >
          执行清理
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default AudioLibraryPurgeDialog
