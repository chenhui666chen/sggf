import { useState } from 'react'
import DeleteIcon from '@mui/icons-material/Delete'
import HistoryIcon from '@mui/icons-material/History'
import PlayIcon from '@mui/icons-material/PlayArrow'
import WarningIcon from '@mui/icons-material/Warning'
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
  List,
  ListItem,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { useFormats } from '@/i18n'

import { audiobookButtonSx, audiobookColorRoles, audiobookColors } from './audiobookTheme'
import type { AudiobookProjectHistoryItem, HistoryDialogProps } from './types'

const getEngineModeLabel = (engineMode: AudiobookProjectHistoryItem['engine_mode'], t: TFunction) => (
  engineMode === 'seed_scene'
    ? t('audiobook.audiobookSetupStep.seedSceneLabel')
    : t('audiobook.audiobookSetupStep.legacyStemsLabel')
)

// 完成阶段标签：剧本-only 批次 status 也是 completed，
// 须按音频落盘章节数区分，避免被误读为整体完成
const getHistoryStatusChip = (project: AudiobookProjectHistoryItem, t: TFunction) => {
  if (project.status === 'processing') {
    return { label: t('audiobook.historyDialog.processingLabel'), chipBg: audiobookColorRoles.taskStatus.running.chipBg }
  }
  if (project.status === 'failed') {
    return { label: t('audiobook.historyDialog.failedLabel'), chipBg: audiobookColorRoles.taskStatus.failed.chipBg }
  }
  if (project.status === 'completed') {
    const totalChapters = project.total_chapters || 0
    const audioCompleted = project.audio_completed_chapters || 0
    if (totalChapters > 0 && audioCompleted >= totalChapters) {
      return { label: t('audiobook.historyDialog.allCompleted'), chipBg: audiobookColorRoles.taskStatus.completed.chipBg }
    }
    if (audioCompleted > 0) {
      return { label: t('audiobook.historyDialog.partialCompleted'), chipBg: audiobookColors.warningMain }
    }
    return { label: t('audiobook.historyDialog.scriptOnlyCompleted'), chipBg: audiobookColorRoles.notice.warning.text }
  }
  return { label: t('audiobook.historyDialog.pendingLabel'), chipBg: audiobookColorRoles.taskStatus.pending.chipBg }
}

const HistoryDialog = ({
  open,
  loading,
  historyProjects,
  selectedProject,
  onCloseHistory,
  onViewHistory,
  onDeleteHistory,
}: HistoryDialogProps) => {
  const { formatDateTime } = useFormats()
  const { t } = useTranslation()
  const [deleteProjectId, setDeleteProjectId] = useState<number | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteReason, setDeleteReason] = useState('')
  const [deleteFiles, setDeleteFiles] = useState(true)
  const [deleting, setDeleting] = useState(false)

  const handleOpenDeleteDialog = (projectId: number) => {
    setDeleteProjectId(projectId)
    setDeleteDialogOpen(true)
    setDeleteReason('')
    setDeleteFiles(true)
  }

  const handleCloseDeleteDialog = () => {
    setDeleteDialogOpen(false)
    setDeleteProjectId(null)
    setDeleteReason('')
    setDeleteFiles(true)
  }

  const handleConfirmDelete = async () => {
    if (!deleteProjectId) return
    setDeleting(true)
    try {
      await onDeleteHistory(deleteProjectId, { delete_reason: deleteReason || undefined, delete_files: deleteFiles })
      handleCloseDeleteDialog()
    } finally {
      setDeleting(false)
    }
  }

  const formatProjectCreatedAt = (value: string | null | undefined) => {
    if (!value) {
      return t('audiobook.historyDialog.unknownTime')
    }

    const timestamp = Date.parse(value)
    if (!Number.isFinite(timestamp)) {
      return t('audiobook.historyDialog.unknownTime')
    }

    return formatDateTime(timestamp)
  }

  return (
    <>
      <Dialog open={open} onClose={onCloseHistory} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon sx={{ color: audiobookColors.brand }} />
            <Typography variant="h6">
              {t('audiobook.historyDialog.historyTitle', { title: selectedProject?.title || '' })}
            </Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : historyProjects.length === 0 ? (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography variant="body2" color="text.secondary">
                {t('audiobook.historyDialog.emptyHistory')}
              </Typography>
            </Box>
          ) : (
            <List>
              {historyProjects.map((project) => {
                const statusChip = getHistoryStatusChip(project, t)
                const audioCompleted = project.audio_completed_chapters || 0
                return (
                <ListItem
                  key={project.id}
                  sx={{
                    border: `1px solid ${audiobookColorRoles.taskStatus.pending.border}`,
                    borderRadius: 2,
                    mb: 2,
                    '&:hover': {
                      backgroundColor: audiobookColors.brandSoft,
                      cursor: 'pointer',
                    },
                  }}
                  onClick={() => onViewHistory(project.id)}
                >
                  <Box sx={{ flex: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
                      <Chip
                        label={statusChip.label}
                        size="small"
                        sx={{
                          backgroundColor: statusChip.chipBg,
                          color: 'white',
                        }}
                      />
                      <Chip
                        label={getEngineModeLabel(project.engine_mode, t)}
                        size="small"
                        variant="outlined"
                        sx={{ color: audiobookColors.brand, borderColor: audiobookColors.brand }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        {formatProjectCreatedAt(project.created_at)}
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                      <Typography variant="body2">
                        {t('audiobook.historyDialog.scriptCount', {
                          done: project.completed_chapters,
                          total: project.total_chapters,
                        })}
                      </Typography>
                      <Typography
                        variant="body2"
                        color={audioCompleted > 0 ? 'text.primary' : undefined}
                        sx={audioCompleted > 0 ? undefined : { color: audiobookColorRoles.notice.warning.text }}
                      >
                        {t('audiobook.historyDialog.audioCount', {
                          done: audioCompleted,
                          total: project.total_chapters,
                        })}
                      </Typography>
                      {audioCompleted > 0 && (
                        <Typography variant="body2" color="text.secondary">
                          {t('audiobook.historyDialog.durationLabel', {
                            minutes: ((project.total_duration || 0) / 60).toFixed(1),
                          })}
                        </Typography>
                      )}
                    </Box>
                  </Box>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <IconButton
                      edge="end"
                      onClick={(event) => {
                        event.stopPropagation()
                        onViewHistory(project.id)
                      }}
                      sx={{ color: audiobookColors.brand }}
                    >
                      <PlayIcon />
                    </IconButton>
                    <IconButton
                      edge="end"
                      onClick={(event) => {
                        event.stopPropagation()
                        handleOpenDeleteDialog(project.id)
                      }}
                      sx={{ color: audiobookColorRoles.destructiveAction.main }}
                    >
                      <DeleteIcon />
                    </IconButton>
                  </Box>
                </ListItem>
                )
              })}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={onCloseHistory}>{t('action.close')}</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteDialogOpen} onClose={handleCloseDeleteDialog} maxWidth="sm" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <WarningIcon sx={{ color: audiobookColorRoles.destructiveAction.main }} />
            <Typography variant="h6">{t('audiobook.historyDialog.deleteConfirmTitle')}</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            {t('audiobook.historyDialog.deleteWarning')}
          </Alert>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('audiobook.historyDialog.projectIdLabel', { id: deleteProjectId })}
          </Typography>
          <TextField
            fullWidth
            multiline
            rows={3}
            label={t('audiobook.historyDialog.deleteReasonLabel')}
            placeholder={t('audiobook.historyDialog.deleteReasonPlaceholder')}
            value={deleteReason}
            onChange={(event) => setDeleteReason(event.target.value)}
            sx={{ mb: 2 }}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={deleteFiles}
                onChange={(event) => setDeleteFiles(event.target.checked)}
                sx={{
                  color: audiobookColorRoles.destructiveAction.main,
                  '&.Mui-checked': {
                    color: audiobookColorRoles.destructiveAction.main,
                  },
                }}
              />
            }
            label={t('audiobook.historyDialog.deleteFilesLabel')}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDeleteDialog} disabled={deleting}>{t('action.cancel')}</Button>
          <Button
            onClick={handleConfirmDelete}
            disabled={deleting}
            variant="contained"
            startIcon={deleting ? <CircularProgress size={18} color="inherit" /> : undefined}
            sx={audiobookButtonSx.dangerContained}
          >
            {deleting ? t('audiobook.historyDialog.deletingText') : t('audiobook.historyDialog.deleteConfirmAction')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

export default HistoryDialog
