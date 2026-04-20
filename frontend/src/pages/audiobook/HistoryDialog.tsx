import { useState } from 'react'
import DeleteIcon from '@mui/icons-material/Delete'
import HistoryIcon from '@mui/icons-material/History'
import PlayIcon from '@mui/icons-material/PlayArrow'
import WarningIcon from '@mui/icons-material/Warning'
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
  IconButton,
  List,
  ListItem,
  Typography,
} from '@mui/material'

import type { HistoryDialogProps } from './types'

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

  const handleOpenDeleteDialog = (projectId: number) => {
    setDeleteProjectId(projectId)
    setDeleteDialogOpen(true)
  }

  const handleCloseDeleteDialog = () => {
    setDeleteDialogOpen(false)
    setDeleteProjectId(null)
  }

  const handleConfirmDelete = async () => {
    if (deleteProjectId) {
      await onDeleteHistory(deleteProjectId)
      handleCloseDeleteDialog()
    }
  }

  return (
    <>
      <Dialog open={open} onClose={onCloseHistory} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon sx={{ color: '#9c27b0' }} />
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
              {historyProjects.map((project) => (
                <ListItem
                  key={project.id}
                  sx={{
                    border: '1px solid #e0e0e0',
                    borderRadius: 2,
                    mb: 2,
                    '&:hover': {
                      backgroundColor: 'rgba(156, 39, 176, 0.05)',
                      cursor: 'pointer',
                    },
                  }}
                  onClick={() => onViewHistory(project.id)}
                >
                  <Box sx={{ flex: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                      <Chip
                        label={
                          project.status === 'completed'
                            ? '已完成'
                            : project.status === 'processing'
                            ? '生成中'
                            : project.status === 'failed'
                            ? '失败'
                            : '等待中'
                        }
                        size="small"
                        sx={{
                          backgroundColor:
                            project.status === 'completed'
                              ? '#4caf50'
                              : project.status === 'processing'
                              ? '#ff9800'
                              : project.status === 'failed'
                              ? '#f44336'
                              : '#9e9e9e',
                          color: 'white',
                        }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        {new Date(project.created_at).toLocaleString('zh-CN', {
                          year: 'numeric',
                          month: '2-digit',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 2 }}>
                      <Typography variant="body2">
                        章节：{project.completed_chapters}/{project.total_chapters}
                      </Typography>
                      {project.status === 'completed' && (
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
                      sx={{ color: '#9c27b0' }}
                    >
                      <PlayIcon />
                    </IconButton>
                    <IconButton
                      edge="end"
                      onClick={(event) => {
                        event.stopPropagation()
                        handleOpenDeleteDialog(project.id)
                      }}
                      sx={{ color: '#f44336' }}
                    >
                      <DeleteIcon />
                    </IconButton>
                  </Box>
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={onCloseHistory}>关闭</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteDialogOpen} onClose={handleCloseDeleteDialog}>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <WarningIcon sx={{ color: '#f44336' }} />
            <Typography variant="h6">确认删除</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            此操作将永久删除该有声书项目！
          </Alert>
          <Typography variant="body1" sx={{ mb: 2 }}>
            确定要删除这个有声书项目吗？
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            项目ID: {deleteProjectId}
          </Typography>
          <Alert severity="info" sx={{ mb: 2 }}>
            将默认同时删除音频文件（不可恢复）。
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDeleteDialog}>取消</Button>
          <Button
            onClick={handleConfirmDelete}
            variant="contained"
            sx={{
              backgroundColor: '#f44336',
              '&:hover': { backgroundColor: '#d32f2f' },
            }}
          >
            确认删除
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

export default HistoryDialog
