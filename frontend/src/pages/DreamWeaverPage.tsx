import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import { logout } from '@/store/slices/authSlice'
import { apiClient } from '@/services/api'
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  Chip,
  CircularProgress,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  IconButton,
  InputAdornment,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import MovieIcon from '@mui/icons-material/Movie'
import PhotoLibraryIcon from '@mui/icons-material/PhotoLibrary'
import SearchIcon from '@mui/icons-material/Search'
import ScienceIcon from '@mui/icons-material/Science'
import LogoutIcon from '@mui/icons-material/Logout'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'

interface Project {
  id: number
  title: string
  description?: string
  genre?: string
}

const perforationHoles = Array.from({ length: 8 })

function FilmPerforationColumn() {
  return (
    <Box
      aria-hidden
      sx={{
        width: 18,
        backgroundColor: 'rgba(0,0,0,0.35)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-around',
        alignItems: 'center',
        py: 1,
      }}
    >
      {perforationHoles.map((_, idx) => (
        <Box
          key={idx}
          sx={{
            width: 10,
            height: 10,
            borderRadius: 1,
            backgroundColor: 'rgba(255,255,255,0.18)',
          }}
        />
      ))}
    </Box>
  )
}

export default function DreamWeaverPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()

  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedGenre, setSelectedGenre] = useState<string>('all')
  const [actionAlert, setActionAlert] = useState<{ severity: 'success' | 'error'; message: string } | null>(null)
  const [purgeDialogOpen, setPurgeDialogOpen] = useState(false)
  const [purgeTarget, setPurgeTarget] = useState<Project | null>(null)
  const [purgeSubmitting, setPurgeSubmitting] = useState(false)
  const [purgeDialogError, setPurgeDialogError] = useState<string | null>(null)

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        setLoading(true)
        const res = await apiClient.getProjects()
        setProjects((res.data as Project[]) || [])
      } catch (e: any) {
        setError(e?.message || '获取项目失败，请稍后重试')
      } finally {
        setLoading(false)
      }
    }
    fetchProjects()
  }, [])

  const genreOptions = useMemo(() => {
    const set = new Set<string>()
    projects.forEach((p) => {
      if (p.genre) set.add(p.genre)
    })
    return Array.from(set)
  }, [projects])

  const filteredProjects = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return projects.filter((p) => {
      if (selectedGenre !== 'all' && (p.genre || '') !== selectedGenre) return false
      if (!q) return true
      const hay = `${p.title || ''}\n${p.description || ''}\n${p.genre || ''}`.toLowerCase()
      return hay.includes(q)
    })
  }, [projects, searchQuery, selectedGenre])

  const handleLogout = () => {
    dispatch(logout())
    navigate('/login')
  }

  const openPurgeDialog = (project: Project) => {
    setPurgeTarget(project)
    setPurgeDialogError(null)
    setPurgeDialogOpen(true)
  }

  const closePurgeDialog = () => {
    if (purgeSubmitting) return
    setPurgeDialogOpen(false)
    setPurgeTarget(null)
    setPurgeDialogError(null)
  }

  const confirmPurgeDialog = async () => {
    if (!purgeTarget) return
    setPurgeSubmitting(true)
    setPurgeDialogError(null)
    try {
      const res = await apiClient.deleteDreamweaverProjectGenerated(purgeTarget.id)
      const deletedRuns = Array.isArray(res.data?.deleted_runs) ? res.data.deleted_runs.length : 0
      const skippedRuns = Array.isArray(res.data?.skipped_runs) ? res.data.skipped_runs.length : 0
      const librarySkipped = Boolean(res.data?.library_skipped)
      const deletedLibraryDir = Boolean(res.data?.deleted_library_dir)
      const deletedLibraryAssets = Number(res.data?.deleted_library_assets || 0)
      const failedPaths = Array.isArray(res.data?.failed_paths) ? res.data.failed_paths : []
      setActionAlert({
        severity: 'success',
        message: `清理完成：已删除 ${deletedRuns} 个 run；跳过 ${skippedRuns} 个；素材库${
          librarySkipped
            ? '未清理（存在运行中/排队任务）'
            : (deletedLibraryDir || deletedLibraryAssets > 0)
              ? '已清理'
              : '无可清理'
        }${failedPaths.length ? `；失败路径 ${failedPaths.length} 个` : ''}`,
      })
      setPurgeDialogOpen(false)
      setPurgeTarget(null)
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const msg =
        (detail && typeof detail === 'object' && typeof detail.message === 'string' && detail.message) ||
        (typeof detail === 'string' && detail) ||
        e?.message ||
        '清理失败，请稍后重试'
      setPurgeDialogError(msg)
      setActionAlert({ severity: 'error', message: msg })
    } finally {
      setPurgeSubmitting(false)
    }
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #6b7280 0%, #4b5563 50%, #374151 100%)',
        position: 'relative',
      }}
    >
      {/* 顶部标题栏（对齐灵感方舟 / 耳畔星河） */}
      <Box
        sx={{
          background: 'linear-gradient(135deg, #1976d2 0%, #1565c0 100%)',
          py: 3,
          px: 3,
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        }}
      >
        <Container maxWidth="lg">
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <IconButton
                onClick={() => navigate('/home')}
                sx={{
                  color: 'white',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                  '&:hover': { backgroundColor: 'rgba(255,255,255,0.2)' },
                }}
                title="返回创作工坊"
              >
                <ArrowBackIcon />
              </IconButton>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <MovieIcon sx={{ fontSize: 32, color: 'white' }} />
                <Box>
                  <Typography variant="h5" sx={{ color: 'white', fontWeight: 700, letterSpacing: '0.5px' }}>
                    织梦映心
                  </Typography>
                  <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.8)', fontSize: '0.85rem' }}>
                    短剧创作 · 选择项目进入生成流程
                  </Typography>
                </Box>
              </Box>
            </Box>

            <Box sx={{ display: 'flex', gap: 1.5 }}>
              <Button
                variant="outlined"
                startIcon={<ScienceIcon />}
                onClick={() => navigate('/prompt-evolution')}
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  '&:hover': { borderColor: 'white', backgroundColor: 'rgba(255,255,255,0.1)' },
                }}
              >
                提示词优化
              </Button>
              <Button
                variant="outlined"
                startIcon={<LogoutIcon />}
                onClick={handleLogout}
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  '&:hover': { borderColor: 'white', backgroundColor: 'rgba(255,255,255,0.1)' },
                }}
              >
                退出登录
              </Button>
            </Box>
          </Box>
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        {/* 搜索 + 题材筛选 */}
        <Box
          sx={{
            mb: 3,
            p: 2,
            borderRadius: 2,
            backgroundColor: 'rgba(255,255,255,0.08)',
            border: '1px solid rgba(255,255,255,0.12)',
          }}
        >
          <TextField
            placeholder="搜索项目..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            size="small"
            fullWidth
            sx={{
              mb: 2,
              '& .MuiOutlinedInput-root': {
                color: 'rgba(255,255,255,0.92)',
                backgroundColor: 'rgba(0,0,0,0.15)',
                '& fieldset': { borderColor: 'rgba(255,255,255,0.25)' },
                '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.35)' },
                '&.Mui-focused fieldset': { borderColor: 'rgba(255,255,255,0.5)' },
              },
              '& .MuiInputAdornment-root': { color: 'rgba(255,255,255,0.65)' },
            }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon />
                </InputAdornment>
              ),
            }}
          />

          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Chip
              label="全部"
              clickable
              onClick={() => setSelectedGenre('all')}
              sx={{
                color: selectedGenre === 'all' ? '#111827' : 'rgba(255,255,255,0.9)',
                backgroundColor: selectedGenre === 'all' ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.18)',
                '&:hover': { backgroundColor: selectedGenre === 'all' ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.24)' },
              }}
            />
            {genreOptions.map((g) => (
              <Chip
                key={g}
                label={g}
                clickable
                onClick={() => setSelectedGenre(g)}
                sx={{
                  color: selectedGenre === g ? '#111827' : 'rgba(255,255,255,0.9)',
                  backgroundColor: selectedGenre === g ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.18)',
                  '&:hover': { backgroundColor: selectedGenre === g ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.24)' },
                }}
              />
            ))}
          </Box>
        </Box>

        {actionAlert && (
          <Alert severity={actionAlert.severity} sx={{ mb: 2 }} onClose={() => setActionAlert(null)}>
            {actionAlert.message}
          </Alert>
        )}

        {error && (
          <Box sx={{ mb: 2 }}>
            <Typography color="error">{error}</Typography>
          </Box>
        )}

        {loading ? (
          <Box sx={{ py: 8, display: 'flex', justifyContent: 'center' }}>
            <CircularProgress />
          </Box>
        ) : filteredProjects.length ? (
          <Grid container spacing={3}>
            {filteredProjects.map((project) => (
              <Grid item xs={12} sm={6} md={4} lg={3} key={project.id}>
                <Card
                  sx={{
                    borderRadius: 3,
                    overflow: 'hidden',
                    backgroundColor: 'rgba(0,0,0,0.18)',
                    border: '1px solid rgba(255,255,255,0.12)',
                    boxShadow: '0 10px 24px rgba(0,0,0,0.18)',
                    transition: 'transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
                    '&:hover': {
                      transform: 'translateY(-4px)',
                      boxShadow: '0 14px 30px rgba(0,0,0,0.26)',
                      borderColor: 'rgba(255,255,255,0.2)',
                    },
                  }}
                >
                  <CardActionArea
                    title="进入生成流程"
                    onClick={() => navigate(`/drama/${project.id}`)}
                    sx={{ display: 'block' }}
                  >
                    {/* 场记板顶条 */}
                    <Box
                      sx={{
                        height: 34,
                        background:
                          'repeating-linear-gradient(135deg, rgba(17,24,39,0.95) 0 12px, rgba(229,231,235,0.95) 12px 24px)',
                        borderBottom: '1px solid rgba(255,255,255,0.12)',
                      }}
                    />
                    {/* 胶片主体 */}
                    <Box
                      sx={{
                        display: 'flex',
                        minHeight: 190,
                        background: 'linear-gradient(135deg, rgba(17,24,39,0.88) 0%, rgba(55,65,81,0.88) 100%)',
                      }}
                    >
                      <FilmPerforationColumn />
                      <Box sx={{ flex: 1, px: 2, py: 1.75 }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1 }}>
                          <Chip
                            size="small"
                            label="DRAMA"
                            sx={{
                              height: 22,
                              fontWeight: 700,
                              letterSpacing: '0.6px',
                              color: 'rgba(255,255,255,0.9)',
                              backgroundColor: 'rgba(245,158,11,0.18)',
                              border: '1px solid rgba(245,158,11,0.35)',
                            }}
                          />
                          {project.genre && (
                            <Chip
                              size="small"
                              label={project.genre}
                              sx={{
                                height: 22,
                                color: 'rgba(255,255,255,0.85)',
                                backgroundColor: 'rgba(255,255,255,0.12)',
                                border: '1px solid rgba(255,255,255,0.18)',
                              }}
                            />
                          )}
                        </Box>

                        <Typography
                          variant="subtitle1"
                          sx={{
                            mt: 1,
                            fontWeight: 700,
                            color: 'rgba(255,255,255,0.95)',
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }}
                        >
                          {project.title}
                        </Typography>
                        <Typography
                          variant="body2"
                          sx={{
                            mt: 0.75,
                            color: 'rgba(255,255,255,0.75)',
                            display: '-webkit-box',
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }}
                        >
                          {project.description || '从项目章节生成剧本、分镜与视频片段'}
                        </Typography>

                        <Box sx={{ mt: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.65)' }}>
                            点击进入生成流程
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 1 }}>
                            <Tooltip title="进入素材库" placement="top" arrow>
                              <IconButton
                                size="small"
                                onClick={(e) => {
                                  e.preventDefault()
                                  e.stopPropagation()
                                  navigate(`/drama/${project.id}/library`)
                                }}
                                sx={{
                                  width: 28,
                                  height: 28,
                                  borderRadius: '50%',
                                  backgroundColor: 'rgba(245,158,11,0.18)',
                                  border: '1px solid rgba(245,158,11,0.35)',
                                  color: 'rgba(255,255,255,0.9)',
                                  '&:hover': { backgroundColor: 'rgba(245,158,11,0.28)' },
                                }}
                                aria-label="进入素材库"
                              >
                                <PhotoLibraryIcon sx={{ fontSize: 18 }} />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="删除生成内容" placement="top" arrow>
                              <IconButton
                                size="small"
                                onClick={(e) => {
                                  e.preventDefault()
                                  e.stopPropagation()
                                  openPurgeDialog(project)
                                }}
                                disabled={purgeSubmitting && purgeTarget?.id === project.id}
                                sx={{
                                  width: 28,
                                  height: 28,
                                  borderRadius: '50%',
                                  backgroundColor: 'rgba(239,68,68,0.18)',
                                  border: '1px solid rgba(239,68,68,0.35)',
                                  color: 'rgba(255,255,255,0.9)',
                                  '&:hover': { backgroundColor: 'rgba(239,68,68,0.28)' },
                                }}
                                aria-label="删除生成内容"
                              >
                                <DeleteOutlineIcon sx={{ fontSize: 18 }} />
                              </IconButton>
                            </Tooltip>
                          </Box>
                        </Box>
                      </Box>
                      <FilmPerforationColumn />
                    </Box>
                  </CardActionArea>
                </Card>
              </Grid>
            ))}
          </Grid>
        ) : (
          <Box sx={{ py: 8, textAlign: 'center' }}>
            <Typography sx={{ color: 'rgba(255,255,255,0.85)', fontWeight: 600 }}>
              未找到匹配的项目
            </Typography>
            <Typography sx={{ color: 'rgba(255,255,255,0.65)', mt: 1 }}>
              可前往“灵感方舟”创建项目并生成章节后再回来开始短剧制作。
            </Typography>
            <Button
              sx={{ mt: 2 }}
              variant="contained"
              onClick={() => navigate('/dashboard')}
            >
              前往灵感方舟
            </Button>
          </Box>
        )}

        <Dialog
          open={purgeDialogOpen}
          onClose={closePurgeDialog}
          fullWidth
          maxWidth="sm"
        >
          <DialogTitle>删除生成内容：{purgeTarget?.title || '-'}</DialogTitle>
          <DialogContent dividers>
            <Alert severity="warning" sx={{ mb: 2 }}>
              此操作不可恢复，将清理该项目已生成的内容（历史 runs 与素材库图片）。
            </Alert>
            <Typography variant="body2" color="text.secondary">
              将删除：
            </Typography>
            <Typography variant="body2" sx={{ mt: 1, whiteSpace: 'pre-wrap' }}>
              - 历史 runs（数据库记录 + runs/{'{run_id}'} 产物文件）
              - 素材库图片（runs/library/project_{'{project_id}'}）
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              注意：运行中/排队中的 run 会跳过；若存在运行/排队任务，将不会清理素材库以避免影响任务。
            </Typography>
            {purgeDialogError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {purgeDialogError}
              </Alert>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={closePurgeDialog} disabled={purgeSubmitting}>
              取消
            </Button>
            <Button variant="contained" color="error" onClick={confirmPurgeDialog} disabled={purgeSubmitting || !purgeTarget}>
              {purgeSubmitting ? '删除中…' : '确认删除'}
            </Button>
          </DialogActions>
        </Dialog>
      </Container>
    </Box>
  )
}
