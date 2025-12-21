import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Container,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { apiClient } from '@/services/api'

interface Project {
  id: number
  title: string
  description?: string
}

interface Chapter {
  id: number
  chapter_number: number
  title: string
  content: string
}

interface MockResult {
  run_id: string
  state: string
  stage?: string | null
  progress?: number | null
  artifacts?: Record<string, any> | null
  source_chapter_count: number
  plan?: Record<string, any>
  storyboard?: any[]
  keyframes?: any[]
  midframes?: any[]
  video_clips?: any[]
  merged_video?: string | null
  audit?: Record<string, any>
}

interface MockTaskStatus {
  task_id: string
  status: 'running' | 'completed' | 'failed'
  progress: number
  run_id?: string | null
  state?: string | null
  stage?: string | null
  artifacts?: Record<string, any> | null
  error_type?: string | null
  result?: MockResult | null
  error?: string | null
}

export default function DreamWeaverMockPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [selectedChapterIds, setSelectedChapterIds] = useState<number[]>([])
  const [loadingProjects, setLoadingProjects] = useState(false)
  const [loadingChapters, setLoadingChapters] = useState(false)
  const [running, setRunning] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskRunId, setTaskRunId] = useState<string | null>(null)
  const [taskProgress, setTaskProgress] = useState<number>(0)
  const [taskState, setTaskState] = useState<string | null>(null)
  const [taskStage, setTaskStage] = useState<string | null>(null)
  const [taskArtifacts, setTaskArtifacts] = useState<Record<string, any> | null>(null)
  const [result, setResult] = useState<MockResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const formatPath = (value: any) => {
    if (!value || typeof value !== 'string') return null
    const parts = value.split(/[\\/]+/).filter(Boolean)
    return parts.slice(-2).join('/')
  }

  const formatPaths = (value: any) => {
    if (!Array.isArray(value)) return null
    const formatted = value.map(formatPath).filter(Boolean)
    return formatted.length ? formatted.join('  ') : null
  }

  const copyDebugInfo = async () => {
    const payload = {
      page: 'DreamWeaverMockPage',
      selectedProjectId,
      selectedChapterIds,
      running,
      task: {
        taskId,
        runId: taskRunId,
        progress: taskProgress,
        state: taskState,
        stage: taskStage,
        artifacts: taskArtifacts,
      },
      error,
      result,
    }

    const text = JSON.stringify(payload, null, 2)
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      window.prompt('复制以下调试信息：', text)
    }
  }

  useEffect(() => {
    const loadProjects = async () => {
      setLoadingProjects(true)
      try {
        const res = await apiClient.getProjects()
        setProjects(res.data || [])
      } catch (e: any) {
        setError(e?.message || '获取项目列表失败')
      } finally {
        setLoadingProjects(false)
      }
    }
    loadProjects()
  }, [])

  useEffect(() => {
    if (!taskId) return

    let cancelled = false
    let timer: any = null

    const poll = async () => {
      try {
        const res = await apiClient.getDreamweaverMockTask(taskId)
        const data = res.data as MockTaskStatus
        if (cancelled) return

        if (data.status === 'running') {
          setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
          setTaskState(data.state || null)
          setTaskStage(data.stage || null)
          setTaskArtifacts((data.artifacts as any) || null)
          setTaskRunId((prev) => data.run_id || prev)
          timer = setTimeout(poll, 1000)
          return
        }

        setRunning(false)
        setTaskId(null)
        setTaskRunId(null)
        setTaskProgress(0)
        setTaskState(null)
        setTaskStage(null)
        setTaskArtifacts(null)

        if (data.status === 'completed') {
          setResult((data.result as any) || null)
        } else {
          setError(data.error || 'Mock 任务执行失败')
        }
      } catch (e: any) {
        if (cancelled) return
        setRunning(false)
        setTaskId(null)
        setTaskRunId(null)
        setTaskProgress(0)
        setTaskState(null)
        setTaskStage(null)
        setTaskArtifacts(null)
        setError(e?.response?.data?.detail || e?.message || 'Mock 任务状态查询失败')
      }
    }

    poll()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [taskId])

  const handleSelectProject = async (projectId: number) => {
    setSelectedProjectId(projectId)
    setResult(null)
    setError(null)
    setLoadingChapters(true)
    try {
      const res = await apiClient.getChapters(projectId)
      const data = res.data as Chapter[]
      setChapters(data)
      setSelectedChapterIds(data.map((c) => c.id))
    } catch (e: any) {
      setError(e?.message || '加载章节失败')
      setChapters([])
      setSelectedChapterIds([])
    } finally {
      setLoadingChapters(false)
    }
  }

  const handleToggleChapter = (chapterId: number) => {
    setSelectedChapterIds((prev) =>
      prev.includes(chapterId) ? prev.filter((id) => id !== chapterId) : [...prev, chapterId],
    )
  }

  const handleSelectAll = () => {
    if (selectedChapterIds.length === chapters.length) {
      setSelectedChapterIds([])
    } else {
      setSelectedChapterIds(chapters.map((c) => c.id))
    }
  }

  const handleRunMock = async () => {
    if (!selectedProjectId || selectedChapterIds.length === 0) {
      setError('请选择项目与至少一个章节后再开始体验')
      return
    }
    setRunning(true)
    setTaskId(null)
    setTaskRunId(null)
    setTaskProgress(0)
    setTaskState(null)
    setTaskStage(null)
    setTaskArtifacts(null)
    setResult(null)
    setError(null)
    try {
      const res = await apiClient.runDreamweaverMockAsync(selectedProjectId, selectedChapterIds)
      const data = res.data as { task_id: string; run_id: string; status: string }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Mock 任务提交失败')
      setRunning(false)
    } finally {
      // running 状态由轮询结束时关闭
    }
  }

  const previewText = useMemo(() => {
    return chapters
      .filter((c) => selectedChapterIds.includes(c.id))
      .map((c) => `${c.title || `第${c.chapter_number}章`}\n${(c.content || '').slice(0, 500)}`)
      .join('\n\n')
  }, [chapters, selectedChapterIds])

  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', py: 4 }}>
      <Container maxWidth="lg">
        <Button
          variant="text"
          startIcon={<ArrowBackIcon />}
          sx={{ color: 'white', mb: 2 }}
          onClick={() => navigate('/drama')}
        >
          返回织梦映心
        </Button>

        <Typography variant="h4" sx={{ color: 'white', fontWeight: 700, mb: 0.5 }}>
          织梦映心 · Mock流程
        </Typography>
        <Typography variant="body1" sx={{ color: 'rgba(255,255,255,0.85)', mb: 3 }}>
          直接读取“灵感方舟”项目的章节内容，跑通短剧 Mock 状态机，快速查看首尾帧、占位视频等产物。
        </Typography>

        <Grid container spacing={2.5}>
          <Grid item xs={12} md={4}>
            <Card sx={{ borderRadius: 3, boxShadow: '0 12px 24px rgba(0,0,0,0.15)' }}>
              <CardContent>
                <Stack direction="row" alignItems="center" spacing={1} mb={2}>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    灵感方舟 · 项目
                  </Typography>
                  {loadingProjects && <LinearProgress sx={{ flex: 1 }} />}
                </Stack>
                <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                  <InputLabel id="project-select-label">选择项目</InputLabel>
                  <Select
                    labelId="project-select-label"
                    value={selectedProjectId ?? ''}
                    label="选择项目"
                    onChange={(e) => handleSelectProject(Number(e.target.value))}
                    disabled={loadingProjects}
                  >
                    {projects.map((p) => (
                      <MenuItem key={p.id} value={p.id}>
                        {p.title}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <Stack direction="row" alignItems="center" justifyContent="space-between" mb={1}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                    章节（{chapters.length}）
                  </Typography>
                  <Button size="small" onClick={handleSelectAll} disabled={loadingChapters || !chapters.length}>
                    {selectedChapterIds.length === chapters.length ? '清空' : '全选'}
                  </Button>
                </Stack>
                <Box sx={{ maxHeight: 280, overflow: 'auto', border: '1px solid #eee', borderRadius: 2, p: 1 }}>
                  {loadingChapters ? (
                    <LinearProgress />
                  ) : (
                    <List dense disablePadding>
                      {chapters.map((c) => (
                        <ListItem
                          key={c.id}
                          disablePadding
                          secondaryAction={
                            <Checkbox
                              edge="end"
                              size="small"
                              checked={selectedChapterIds.includes(c.id)}
                              onChange={() => handleToggleChapter(c.id)}
                            />
                          }
                        >
                          <ListItemText
                            primary={`${c.chapter_number}. ${c.title || '未命名章节'}`}
                            secondary={(c.content || '').slice(0, 36) + '...'}
                          />
                        </ListItem>
                      ))}
                    </List>
                  )}
                </Box>

                <Button
                  variant="contained"
                  startIcon={<PlayArrowIcon />}
                  fullWidth
                  sx={{ mt: 2, borderRadius: 2 }}
                  onClick={handleRunMock}
                  disabled={running || !selectedProjectId || selectedChapterIds.length === 0}
                >
                  {running ? '运行中…' : '开始体验（Mock）'}
                </Button>
                <Button
                  variant="text"
                  startIcon={<RefreshIcon />}
                  fullWidth
                  sx={{ mt: 1 }}
                  onClick={() => {
                    if (selectedProjectId) handleSelectProject(selectedProjectId)
                  }}
                  disabled={loadingChapters || !selectedProjectId}
                >
                  重新加载章节
                </Button>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} md={8}>
            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}

            <Card sx={{ borderRadius: 3, mb: 2 }}>
              <CardContent>
                <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }}>
                  灵感方舟内容预览
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  取用所选章节的文本作为短剧 Mock 的输入提示。
                </Typography>
                <Box
                  sx={{
                    minHeight: 160,
                    maxHeight: 260,
                    overflow: 'auto',
                    p: 2,
                    bgcolor: '#fafafa',
                    borderRadius: 2,
                    border: '1px dashed #ddd',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'monospace',
                    fontSize: 13,
                  }}
                >
                  {previewText || '请选择项目与章节后查看预览'}
                </Box>
              </CardContent>
            </Card>

            <Card sx={{ borderRadius: 3 }}>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center" mb={1}>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    Mock 运行结果
                  </Typography>
                  {running && <LinearProgress variant="determinate" value={Math.max(0, Math.min(100, taskProgress))} sx={{ flex: 1 }} />}
                </Stack>
                {!result ? (
                  running ? (
                    <Box>
                      <Stack direction="row" spacing={1} flexWrap="wrap" mb={1} alignItems="center">
                        {taskRunId && <Chip label={`RunID: ${taskRunId}`} size="small" />}
                        <Chip label={`进度: ${taskProgress}%`} size="small" color="primary" />
                        {taskState && <Chip label={`状态: ${taskState}`} size="small" />}
                        {taskStage && <Chip label={`阶段: ${taskStage}`} size="small" />}
                        {taskArtifacts?.storyboard_count != null && (
                          <Chip label={`SB: ${taskArtifacts.storyboard_count}`} size="small" />
                        )}
                        {taskArtifacts?.keyframes_count != null && (
                          <Chip label={`KF: ${taskArtifacts.keyframes_count}`} size="small" />
                        )}
                        {taskArtifacts?.midframes_count != null && (
                          <Chip label={`MF: ${taskArtifacts.midframes_count}`} size="small" />
                        )}
                        {taskArtifacts?.video_clips_count != null && (
                          <Chip label={`VC: ${taskArtifacts.video_clips_count}`} size="small" />
                        )}
                        <Button
                          size="small"
                          variant="text"
                          startIcon={<ContentCopyIcon fontSize="small" />}
                          onClick={copyDebugInfo}
                        >
                          复制调试信息
                        </Button>
                      </Stack>
                      {(taskArtifacts?.last_keyframe_path || taskArtifacts?.last_midframe_path || taskArtifacts?.last_video_clip_path) && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                          Last: {formatPath(taskArtifacts.last_keyframe_path) ? `KF ${formatPath(taskArtifacts.last_keyframe_path)}` : ''}
                          {formatPath(taskArtifacts.last_midframe_path) ? `  MF ${formatPath(taskArtifacts.last_midframe_path)}` : ''}
                          {formatPath(taskArtifacts.last_video_clip_path) ? `  VC ${formatPath(taskArtifacts.last_video_clip_path)}` : ''}
                        </Typography>
                      )}
                      {(taskArtifacts?.keyframes_tail_paths || taskArtifacts?.midframes_tail_paths || taskArtifacts?.video_clips_tail_paths) && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                          {formatPaths(taskArtifacts.keyframes_tail_paths) ? `KF: ${formatPaths(taskArtifacts.keyframes_tail_paths)}` : ''}
                          {formatPaths(taskArtifacts.midframes_tail_paths) ? `  MF: ${formatPaths(taskArtifacts.midframes_tail_paths)}` : ''}
                          {formatPaths(taskArtifacts.video_clips_tail_paths) ? `  VC: ${formatPaths(taskArtifacts.video_clips_tail_paths)}` : ''}
                        </Typography>
                      )}
                      {taskArtifacts?.rework_reason && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                          Rework: {JSON.stringify(taskArtifacts.rework_reason)}
                        </Typography>
                      )}
                      {taskArtifacts?.stage_artifacts && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                          Stage artifacts: {JSON.stringify(taskArtifacts.stage_artifacts)}
                        </Typography>
                      )}
                      <Typography variant="body2" color="text.secondary">
                        任务执行中，完成后将自动展示分镜/首尾帧/视频占位产物。
                      </Typography>
                      <Accordion sx={{ mt: 1 }}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                            调试面板（Artifacts）
                          </Typography>
                        </AccordionSummary>
                        <AccordionDetails>
                          <Box
                            sx={{
                              whiteSpace: 'pre-wrap',
                              fontFamily: 'monospace',
                              fontSize: 12,
                              bgcolor: '#fafafa',
                              border: '1px solid #eee',
                              borderRadius: 2,
                              p: 1.5,
                            }}
                          >
                            {JSON.stringify(taskArtifacts, null, 2)}
                          </Box>
                        </AccordionDetails>
                      </Accordion>
                    </Box>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      点击“开始体验（Mock）”后，这里会展示状态机各阶段的占位产物。
                    </Typography>
                  )
                ) : (
                  <Box>
                    <Stack direction="row" spacing={1} flexWrap="wrap" mb={1.5} alignItems="center">
                      <Chip label={`RunID: ${result.run_id}`} size="small" />
                      <Chip
                        label={`状态: ${result.state}`}
                        color={result.state === 'DONE' ? 'success' : result.state === 'FAILED' ? 'error' : 'default'}
                        size="small"
                      />
                      {result.progress != null && <Chip label={`进度: ${result.progress}%`} size="small" color="primary" />}
                      {result.stage && <Chip label={`阶段: ${result.stage}`} size="small" />}
                      <Chip label={`章节: ${result.source_chapter_count}`} size="small" />
                      {result.video_clips && <Chip label={`片段: ${result.video_clips.length}`} size="small" color="primary" />}
                      <Button
                        size="small"
                        variant="text"
                        startIcon={<ContentCopyIcon fontSize="small" />}
                        onClick={copyDebugInfo}
                      >
                        复制调试信息
                      </Button>
                    </Stack>

                    <Accordion sx={{ mb: 1.5 }}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                          调试面板（Result）
                        </Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Box
                          sx={{
                            whiteSpace: 'pre-wrap',
                            fontFamily: 'monospace',
                            fontSize: 12,
                            bgcolor: '#fafafa',
                            border: '1px solid #eee',
                            borderRadius: 2,
                            p: 1.5,
                          }}
                        >
                          {JSON.stringify(result, null, 2)}
                        </Box>
                      </AccordionDetails>
                    </Accordion>

                    <Divider sx={{ my: 1.5 }} />

                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                      计划 / 剧本提要
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      {result.plan?.text || '[mock] 未返回文本'}
                    </Typography>

                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                      分镜（storyboard）
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {result.storyboard ? `${result.storyboard.length} 个镜头` : '暂无'}
                    </Typography>

                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
                      视频占位
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {result.video_clips?.map((v, idx) => v.path ? `${idx + 1}. ${v.path}` : '').join('  ') ||
                        (result.merged_video ? result.merged_video : '暂无生成记录')}
                    </Typography>

                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
                      质检
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {result.audit ? JSON.stringify(result.audit) : '未返回审核信息'}
                    </Typography>
                  </Box>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Container>
    </Box>
  )
}
