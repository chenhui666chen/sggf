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

import { audiobookButtonSx, audiobookColorRoles, audiobookColors } from './audiobookTheme'
import type { AudiobookProjectHistoryItem, HistoryDialogProps } from './types'

const getEngineModeLabel = (engineMode: AudiobookProjectHistoryItem['engine_mode']) => (
  engineMode === 'seed_scene' ? '场景生成' : '分轨合成'
)

// 完成阶段标签：剧本-only 批次 status 也是 completed，
// 须按音频落盘章节数区分，避免被误读为整体完成
const getHistoryStatusChip = (project: AudiobookProjectHistoryItem) => {
  if (project.status === 'processing') {
    return { label: '生成中', chipBg: audiobookColorRoles.taskStatus.running.chipBg }
  }
  if (project.status === 'failed') {
    return { label: '失败', chipBg: audiobookColorRoles.taskStatus.failed.chipBg }
  }
  if (project.status === 'completed') {
    const totalChapters = project.total_chapters || 0
    const audioCompleted = project.audio_completed_chapters || 0
    if (totalChapters > 0 && audioCompleted >= totalChapters) {
      return { label: '全部完成', chipBg: audiobookColorRoles.taskStatus.completed.chipBg }
    }
    if (audioCompleted > 0) {
      return { label: '部分完成', chipBg: audiobookColors.warningMain }
    }
    return { label: '剧本完成·音频未生成', chipBg: audiobookColorRoles.notice.warning.text }
  }
  return { label: '等待中', chipBg: audiobookColorRoles.taskStatus.pending.chipBg }
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
      return '时间未知'
    }

    const timestamp = Date.parse(value)
    if (!Number.isFinite(timestamp)) {
      return '时间未知'
    }

    return new Date(timestamp).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <>
      <Dialog open={open} onClose={onCloseHistory} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon sx={{ color: audiobookColors.brand }} />
            <Typography variant="h6">
              {selectedProject?.title} - 历史生成记录
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
                还没有生成过有声书
              </Typography>
            </Box>
          ) : (
            <List>
              {historyProjects.map((project) => {
                const statusChip = getHistoryStatusChip(project)
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
                        label={getEngineModeLabel(project.engine_mode)}
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
                        剧本：{project.completed_chapters}/{project.total_chapters}
                      </Typography>
                      <Typography
                        variant="body2"
                        color={audioCompleted > 0 ? 'text.primary' : undefined}
                        sx={audioCompleted > 0 ? undefined : { color: audiobookColorRoles.notice.warning.text }}
                      >
                        音频：{audioCompleted}/{project.total_chapters}
                      </Typography>
                      {audioCompleted > 0 && (
                        <Typography variant="body2" color="text.secondary">
                          时长：{((project.total_duration || 0) / 60).toFixed(1)}分钟
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
          <Button onClick={onCloseHistory}>关闭</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteDialogOpen} onClose={handleCloseDeleteDialog} maxWidth="sm" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <WarningIcon sx={{ color: audiobookColorRoles.destructiveAction.main }} />
            <Typography variant="h6">确认删除</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            此操作将删除该有声书项目的产出，原始章节内容不受影响。
          </Alert>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            项目ID: {deleteProjectId}
          </Typography>
          <TextField
            fullWidth
            multiline
            rows={3}
            label="删除原因（可选）"
            placeholder="请说明删除原因..."
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
            label="同时删除音频文件（不可恢复）"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDeleteDialog} disabled={deleting}>取消</Button>
          <Button
            onClick={handleConfirmDelete}
            disabled={deleting}
            variant="contained"
            startIcon={deleting ? <CircularProgress size={18} color="inherit" /> : undefined}
            sx={audiobookButtonSx.dangerContained}
          >
            {deleting ? '删除中...' : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

export default HistoryDialog
