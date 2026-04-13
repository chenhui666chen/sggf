import { useEffect, useState } from 'react'
import {
  Container,
  Typography,
  Box,
  Card,
  CardContent,
  Button,
  Grid,
  Alert,
  CircularProgress,
  Chip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
} from '@mui/material'
import DeleteForeverIcon from '@mui/icons-material/DeleteForever'
import RestoreIcon from '@mui/icons-material/Restore'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { useNavigate } from 'react-router-dom'

interface DeletedChapter {
  id: number
  title: string
  content: string
  word_count: number
  project_id: number
  project_name?: string
  deleted_at: string
  created_at: string
}

export default function TrashPage() {
  const navigate = useNavigate()
  const [deletedChapters, setDeletedChapters] = useState<DeletedChapter[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [restoring, setRestoring] = useState<number | null>(null)
  const [permanentlyDeleting, setPermanentlyDeleting] = useState<number | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [chapterToDelete, setChapterToDelete] = useState<DeletedChapter | null>(null)

  const loadDeletedChapters = async () => {
    try {
      setLoading(true)
      setError(null)
      // 获取所有项目的已删除章节
      const response = await apiClient.getDeletedChapters(0) // projectId为0表示获取所有
      setDeletedChapters(response.data || [])
    } catch (err: any) {
      setError(await extractApiErrorMessage(err, '加载回收站失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDeletedChapters()
  }, [])

  const handleRestore = async (chapterId: number) => {
    try {
      setRestoring(chapterId)
      await apiClient.restoreChapter(chapterId)
      await loadDeletedChapters()
    } catch (err: any) {
      setError(await extractApiErrorMessage(err, '恢复章节失败'))
    } finally {
      setRestoring(null)
    }
  }

  const handlePermanentDeleteClick = (chapter: DeletedChapter) => {
    setChapterToDelete(chapter)
    setDeleteDialogOpen(true)
  }

  const handlePermanentDelete = async () => {
    if (!chapterToDelete) return

    try {
      setPermanentlyDeleting(chapterToDelete.id)
      await apiClient.deleteChapter(chapterToDelete.id)
      setDeleteDialogOpen(false)
      await loadDeletedChapters()
    } catch (err: any) {
      setError(await extractApiErrorMessage(err, '永久删除失败'))
    } finally {
      setPermanentlyDeleting(null)
      setChapterToDelete(null)
    }
  }

  const handleNavigateToProject = (projectId: number) => {
    navigate(`/projects/${projectId}`)
  }

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          🗑️ 回收站
        </Typography>
        <Typography variant="body1" color="textSecondary">
          管理所有已删除的章节，可以恢复或永久删除
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress size={40} />
        </Box>
      ) : deletedChapters.length === 0 ? (
        <Alert severity="info">
          回收站为空，没有已删除的章节
        </Alert>
      ) : (
        <Grid container spacing={3}>
          {deletedChapters.map((chapter) => (
            <Grid item xs={12} md={6} key={chapter.id}>
              <Card
                sx={{
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  '&:hover': {
                    boxShadow: 4,
                  },
                }}
              >
                <CardContent sx={{ flex: 1 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                    <Typography variant="h6" component="h2" sx={{ flex: 1 }}>
                      {chapter.title}
                    </Typography>
                    {chapter.project_name && (
                      <Chip
                        label={chapter.project_name}
                        size="small"
                        color="primary"
                        variant="outlined"
                        sx={{ ml: 1, cursor: 'pointer' }}
                        onClick={() => handleNavigateToProject(chapter.project_id)}
                      />
                    )}
                  </Box>

                  <Box sx={{ mb: 2 }}>
                    <Typography variant="body2" color="textSecondary" gutterBottom>
                      📝 {chapter.word_count || 0} 字
                    </Typography>
                    <Typography variant="body2" color="textSecondary" gutterBottom>
                      📅 创建于 {new Date(chapter.created_at).toLocaleString('zh-CN')}
                    </Typography>
                    <Typography variant="body2" color="textSecondary" gutterBottom>
                      🗑️ 删除于 {new Date(chapter.deleted_at).toLocaleString('zh-CN')}
                    </Typography>
                  </Box>

                  <Box
                    sx={{
                      mt: 2,
                      p: 2,
                      bgcolor: 'grey.50',
                      borderRadius: 1,
                      maxHeight: 100,
                      overflow: 'hidden',
                    }}
                  >
                    <Typography variant="body2" color="textSecondary" sx={{ 
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      display: '-webkit-box',
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: 'vertical',
                    }}>
                      {chapter.content || '无内容'}
                    </Typography>
                  </Box>
                </CardContent>

                <Box sx={{ p: 2, pt: 0, display: 'flex', gap: 1 }}>
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={restoring === chapter.id ? <CircularProgress size={16} /> : <RestoreIcon />}
                    onClick={() => handleRestore(chapter.id)}
                    disabled={restoring === chapter.id}
                    fullWidth
                  >
                    {restoring === chapter.id ? '恢复中...' : '恢复'}
                  </Button>
                  <IconButton
                    color="error"
                    onClick={() => handlePermanentDeleteClick(chapter)}
                    disabled={permanentlyDeleting === chapter.id}
                    title="永久删除"
                  >
                    {permanentlyDeleting === chapter.id ? (
                      <CircularProgress size={20} />
                    ) : (
                      <DeleteForeverIcon />
                    )}
                  </IconButton>
                </Box>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* 永久删除确认对话框 */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        aria-labelledby="permanent-delete-dialog-title"
        aria-describedby="permanent-delete-dialog-description"
      >
        <DialogTitle id="permanent-delete-dialog-title">
          确认永久删除
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="permanent-delete-dialog-description">
            你确定要永久删除章节 <strong>"{chapterToDelete?.title}"</strong> 吗？
            <br />
            <br />
            <strong>警告：此操作不可撤销！</strong>
            <br />
            章节将被永久删除，无法恢复。
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)} disabled={permanentlyDeleting !== null}>
            取消
          </Button>
          <Button
            onClick={handlePermanentDelete}
            color="error"
            variant="contained"
            disabled={permanentlyDeleting !== null}
            startIcon={permanentlyDeleting !== null ? <CircularProgress size={16} /> : <DeleteForeverIcon />}
          >
            {permanentlyDeleting !== null ? '删除中...' : '永久删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  )
}
