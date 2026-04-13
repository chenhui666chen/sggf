import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Box,
  TextField,
  Button,
  Typography,
  CircularProgress,
  Snackbar,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  List,
  ListItem,
  ListItemText,
  Divider,
  Menu,
  MenuItem,
  Grid,
  Paper,
  IconButton,
} from '@mui/material'
import SaveIcon from '@mui/icons-material/Save'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import HistoryIcon from '@mui/icons-material/History'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import RestoreIcon from '@mui/icons-material/Restore'
import DescriptionIcon from '@mui/icons-material/Description'
import ArticleIcon from '@mui/icons-material/Article'
import WarningIcon from '@mui/icons-material/Warning'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'

import { RootState, AppDispatch } from '@/store/store'
import {
  fetchChapter,
  setContent,
  updateChapter,
  autoSaveChapter,
  clearDirty,
} from '@/store/slices/editorSlice'
import SettingRecommendations from '@/components/SettingRecommendations'


export default function EditorPage() {
  const { projectId, chapterId } = useParams<{ projectId: string; chapterId: string }>()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { currentChapter, content, isDirty, isSaving, isLoading } = useSelector(
    (state: RootState) => state.editor
  )
  const autoSaveTimer = useRef<NodeJS.Timeout | null>(null)
  const [lastSaved, setLastSaved] = useState<Date | null>(null)

  const [saveMessage, setSaveMessage] = useState<string>('')
  const [saveError, setSaveError] = useState<string>('')

  // 版本历史状态
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false)
  const [revisions, setRevisions] = useState<any[]>([])
  const [loadingRevisions, setLoadingRevisions] = useState(false)

  // 确认恢复对话框状态
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false)
  const [selectedRevision, setSelectedRevision] = useState<any>(null)
  const [restoringRevision, setRestoringRevision] = useState(false)

  // 章节逻辑检查状态
  const [logicCheckDialogOpen, setLogicCheckDialogOpen] = useState(false)
  const [logicCheckResult, setLogicCheckResult] = useState<any | null>(null)
  const [checkingLogic, setCheckingLogic] = useState(false)

  // 🆕 再次优化状态
  const [optimizing, setOptimizing] = useState(false)
  const [optimizeDialogOpen, setOptimizeDialogOpen] = useState(false)
  const [userFeedback, setUserFeedback] = useState('')

  // 🆕 重新生成章节状态
  const [regenerating, setRegenerating] = useState(false)
  const [regenerateDialogOpen, setRegenerateDialogOpen] = useState(false)
  const [regenerateReason, setRegenerateReason] = useState('')

  // 导出菜单状态
  const [exportAnchorEl, setExportAnchorEl] = useState<null | HTMLElement>(null)
  const exportMenuOpen = Boolean(exportAnchorEl)
  const [exporting, setExporting] = useState(false)

  // 推荐设定侧边栏状态
  const [showRecommendations, setShowRecommendations] = useState(true)
  const contentRef = useRef<HTMLTextAreaElement>(null)

  // 📄 计算字数（中文字符数）
  const wordCount = content.replace(/\s/g, '').length
  const charCount = content.length

  // 插入设定到光标位置
  const handleInsertSetting = (settingName: string) => {
    if (!contentRef.current) return

    const textarea = contentRef.current
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const currentContent = content

    // 在光标位置插入设定名称
    const newContent = currentContent.substring(0, start) + settingName + currentContent.substring(end)
    dispatch(setContent(newContent))

    // 恢复光标位置（在插入文本之后）
    setTimeout(() => {
      textarea.focus()
      const newPos = start + settingName.length
      textarea.setSelectionRange(newPos, newPos)
    }, 0)
  }

  useEffect(() => {
    if (chapterId && projectId) {
      // 立即清除旧内容，防止显示错误的数据
      dispatch(setContent(''))

      dispatch(fetchChapter({
        chapterId: parseInt(chapterId),
        projectId: parseInt(projectId)
      }))
    }
  }, [dispatch, chapterId, projectId])

  useEffect(() => {
    if (isDirty) {
      if (autoSaveTimer.current) {
        clearTimeout(autoSaveTimer.current)
      }
      // 🔧 修复：将自动保存间隔从3秒增加到60秒，避免误操作
      autoSaveTimer.current = setTimeout(() => {
        if (chapterId && content) {
          dispatch(autoSaveChapter({
            chapterId: parseInt(chapterId),
            data: { content },
          }))
          setLastSaved(new Date())
        }
      }, 60000) // 60秒 = 1分钟
    }

    return () => {
      if (autoSaveTimer.current) {
        clearTimeout(autoSaveTimer.current)
      }
    }
  }, [isDirty, content, dispatch, chapterId])

  const handleSave = async () => {
    if (chapterId && currentChapter) {
      try {
        // 🆕 显示智能分析提示
        setSaveMessage('💾 正在保存章节并进行智能分析（预计30-60秒）...')
        
        await dispatch(updateChapter({
          chapterId: parseInt(chapterId),
          data: { content },
        }))
        dispatch(clearDirty())
        setLastSaved(new Date()) // 🆕 设置最后保存时间
        
        // 🆕 显示成功信息，说明AI分析在后台进行
        setSaveMessage('✅ 章节已保存！🤖 AI正在后台分析人物、地点、关系...')
        setTimeout(() => setSaveMessage(''), 5000) // 5秒后清除提示
      } catch (error) {
        setSaveError('保存失败，请重试')
        setTimeout(() => setSaveError(''), 3000)
      }
    }
  }

  // 打开版本历史对话框
  const handleOpenHistory = async () => {
    setHistoryDialogOpen(true)
    setLoadingRevisions(true)
    try {
      const response = await fetch(`/api/v1/chapters/${chapterId}/revisions`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      if (response.ok) {
        const data = await response.json()
        setRevisions(data)
      }
    } catch {
      // 加载版本历史失败
    } finally {
      setLoadingRevisions(false)
    }
  }

  // 🆕 打开再次优化对话框
  const handleOpenOptimizeDialog = () => {
    setUserFeedback('')  // 清空之前的意见
    setOptimizeDialogOpen(true)
  }

  // 🆕 确认再次优化
  const handleConfirmOptimize = async () => {
    setOptimizeDialogOpen(false)
    await handleReOptimize(userFeedback.trim())
  }

  // 🆕 再次优化：对当前章节再迭代一次
  const handleReOptimize = async (feedback: string = '') => {
    if (!chapterId || !projectId) return

    setOptimizing(true)
    try {
      const response = await fetch('/api/v1/workflow/optimize-chapter', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({
          project_id: parseInt(projectId),
          chapter_id: parseInt(chapterId),
          current_content: content,  // 使用当前编辑器中的内容
          user_feedback: feedback,   // 🆕 用户额外意见
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || '优化请求失败')
      }

      const data = await response.json()
      setSaveMessage('✨ 已提交优化任务,正在后台处理...（预计30-60秒）')

      // 轮询任务状态
      pollOptimizeTaskStatus(data.task_id)
    } catch (error: any) {
      setSaveError(error.message || '再次优化失败，请稍后重试')
      setOptimizing(false)
    }
  }

  // 🆕 打开重新生成章节对话框
  const handleOpenRegenerateDialog = () => {
    setRegenerateReason('')  // 清空之前的理由
    setRegenerateDialogOpen(true)
  }

  // 🆕 确认重新生成章节
  const handleConfirmRegenerate = async () => {
    setRegenerateDialogOpen(false)
    await handleRegenerateChapter(regenerateReason.trim())
  }

  // 🆕 重新生成章节：完全重新创作章节内容
  const handleRegenerateChapter = async (reason: string = '') => {
    if (!chapterId || !projectId) return

    setRegenerating(true)
    try {
      const response = await fetch('/api/v1/workflow/regenerate-chapter', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({
          project_id: parseInt(projectId),
          chapter_id: parseInt(chapterId),
          reason: reason,  // 重新生成的理由
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || '重新生成请求失败')
      }

      const data = await response.json()
      setSaveMessage('🔄 已提交重新生成任务,正在后台处理...（预计60-120秒）')

      // 轮询任务状态
      pollRegenerateTaskStatus(data.task_id)
    } catch (error: any) {
      setSaveError(error.message || '重新生成章节失败，请稍后重试')
      setRegenerating(false)
    }
  }

  // 轮询重新生成任务状态
  const pollRegenerateTaskStatus = async (taskId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`/api/v1/workflow/task/${taskId}`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })

        if (!response.ok) {
          clearInterval(pollInterval)
          setRegenerating(false)
          setSaveError('获取任务状态失败')
          return
        }

        const data = await response.json()

        if (data.status === 'completed') {
          clearInterval(pollInterval)

          // 解析结果（result 是 JSON 字符串）
          try {
            const result = typeof data.result === 'string' ? JSON.parse(data.result) : data.result

            if (result && result.content) {
              dispatch(setContent(result.content))
              setSaveMessage('✅ 重新生成完成！章节内容已更新')
            } else {
              setSaveError('重新生成结果为空，请重试')
            }
          } catch {
            setSaveError('解析重新生成结果失败')
          }

          setRegenerating(false)
        } else if (data.status === 'failed') {
          clearInterval(pollInterval)
          setSaveError('重新生成失败: ' + (data.error || '未知错误'))
          setRegenerating(false)
        } else if (data.status === 'running') {
          // 更新进度提示
          setSaveMessage(`🔄 重新生成中... (进度: ${data.progress || 50}%)`)
        }
      } catch {
        // 轮询任务状态失败
      }
    }, 2000) // 每2秒轮询一次

    // 10分钟后超时
    setTimeout(() => {
      clearInterval(pollInterval)
      if (regenerating) {
        setRegenerating(false)
        setSaveError('重新生成超时，请重试')
      }
    }, 600000)
  }

  // 轮询优化任务状态
  const pollOptimizeTaskStatus = async (taskId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`/api/v1/workflow/task/${taskId}`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })
        
        if (!response.ok) {
          clearInterval(pollInterval)
          setOptimizing(false)
          setSaveError('获取任务状态失败')
          return
        }
        
        const data = await response.json()
        
        if (data.status === 'completed') {
          clearInterval(pollInterval)
          
          // 解析结果（result 是 JSON 字符串）
          try {
            const result = typeof data.result === 'string' ? JSON.parse(data.result) : data.result
            
            if (result && result.optimized_content) {
              dispatch(setContent(result.optimized_content))
              setSaveMessage(`✅ 优化完成！评分: ${result.original_score || 'N/A'}`)
            } else {
              setSaveError('优化结果为空，请重试')
            }
          } catch {
            setSaveError('解析优化结果失败')
          }
          
          setOptimizing(false)
        } else if (data.status === 'failed') {
          clearInterval(pollInterval)
          setSaveError('优化失败: ' + (data.error || '未知错误'))
          setOptimizing(false)
        } else if (data.status === 'running') {
          // 更新进度提示
          setSaveMessage(`🔄 优化中... (进度: ${data.progress || 50}%)`)
        }
      } catch {
        // 轮询任务状态失败
      }
    }, 2000) // 每2秒轮询一次
    
    // 5分钟后超时
    setTimeout(() => {
      clearInterval(pollInterval)
      if (optimizing) {
        setOptimizing(false)
        setSaveError('优化超时，请重试')
      }
    }, 300000)
  }

  // 运行章节逻辑检查
  const handleCheckLogic = async () => {
    if (!chapterId || !projectId) return
    setCheckingLogic(true)
    try {
      const response = await fetch('/api/v1/ai/check-chapter-logic', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({
          chapter_id: parseInt(chapterId),
          project_id: parseInt(projectId),
        }),
      })
      if (!response.ok) {
        setSaveError('章节逻辑检查失败，请稍后重试')
        return
      }
      const data = await response.json()
      setLogicCheckResult(data)
      setLogicCheckDialogOpen(true)
    } catch {
      setSaveError('调用章节逻辑检查接口时出错，请检查网络连接')
    } finally {
      setCheckingLogic(false)
    }
  }

  // 打开确认恢复对话框
  const handleOpenRestoreConfirm = (revision: any) => {
    setSelectedRevision(revision)
    setConfirmDialogOpen(true)
  }

  // 确认恢复到指定版本
  const handleConfirmRestore = async () => {
    if (!selectedRevision) return

    setRestoringRevision(true)
    try {
      const response = await fetch(`/api/v1/chapters/${chapterId}/revisions/${selectedRevision.id}/restore`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const chapter = await response.json()
        dispatch(setContent(chapter.content))
        dispatch(clearDirty())
        setSaveMessage('✅ 已成功恢复到指定版本')
        setConfirmDialogOpen(false)
        setHistoryDialogOpen(false)
        // 重新加载版本历史
        setTimeout(() => handleOpenHistory(), 500)
      } else {
        setSaveError('❌ 恢复版本失败，请重试')
      }
    } catch {
      setSaveError('恢复版本失败，请检查网络连接')
    } finally {
      setRestoringRevision(false)
    }
  }

  // 导出TXT
  const handleExportTxt = async () => {
    setExportAnchorEl(null)
    setExporting(true)
    try {
      const response = await fetch(`/api/v1/chapters/${chapterId}/export/txt`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${currentChapter?.title || '章节'}.txt`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
        setSaveMessage('📄 TXT文件导出成功')
      } else {
        setSaveError('❌ 导出TXT失败，请重试')
      }
    } catch {
      setSaveError('导出TXT失败，请检查网络连接')
    } finally {
      setExporting(false)
    }
  }

  // 导出DOCX
  const handleExportDocx = async () => {
    setExportAnchorEl(null)
    setExporting(true)
    try {
      const response = await fetch(`/api/v1/chapters/${chapterId}/export/docx`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${currentChapter?.title || '章节'}.docx`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
        setSaveMessage('📝 DOCX文件导出成功')
      } else {
        setSaveError('❌ 导出DOCX失败，请重试')
      }
    } catch {
      setSaveError('导出DOCX失败，请检查网络连接')
    } finally {
      setExporting(false)
    }
  }



  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Button
            startIcon={<ArrowBackIcon />}
            onClick={() => navigate(`/dashboard?projectId=${projectId}`)}
          >
            返回
          </Button>
          <Typography variant="h5">
            {currentChapter?.title || '章节编辑器'}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
          {/* 🆕 显示最后保存时间 */}
          {lastSaved && (
            <Typography variant="caption" color="text.secondary">
              💾 最后保存: {lastSaved.toLocaleTimeString('zh-CN')}
            </Typography>
          )}
          {isDirty && <Typography variant="caption" color="warning.main">未保存的更改</Typography>}
          {isSaving && <CircularProgress size={24} />}

          {/* 版本历史按钮 */}
          <Button
            variant="outlined"
            startIcon={<HistoryIcon />}
            onClick={handleOpenHistory}
            size="small"
          >
            版本历史
          </Button>

          {/* 🆕 再次优化按钮 */}
          <Button
            variant="outlined"
            size="small"
            onClick={handleOpenOptimizeDialog}
            disabled={optimizing || !content}
            startIcon={optimizing ? <CircularProgress size={16} /> : undefined}
            color="secondary"
          >
            {optimizing ? '优化中...' : '再次优化'}
          </Button>

          {/* 🆕 重新生成章节按钮 */}
          <Button
            variant="outlined"
            size="small"
            onClick={handleOpenRegenerateDialog}
            disabled={regenerating || optimizing || checkingLogic}
            startIcon={regenerating ? <CircularProgress size={16} /> : undefined}
            color="error"
          >
            {regenerating ? '生成中...' : '重新生成'}
          </Button>

          {/* 章节逻辑检查按钮 */}
          <Button
            variant="outlined"
            size="small"
            onClick={handleCheckLogic}
            disabled={checkingLogic}
            startIcon={checkingLogic ? <CircularProgress size={16} /> : undefined}
          >
            {checkingLogic ? '检查中...' : '逻辑检查'}
          </Button>

          {/* 导出按钮 */}
          <Button
            variant="outlined"
            startIcon={exporting ? <CircularProgress size={16} /> : <FileDownloadIcon />}
            onClick={(e) => setExportAnchorEl(e.currentTarget)}
            size="small"
            disabled={exporting}
          >
            {exporting ? '导出中...' : '导出'}
          </Button>

          {/* 导出菜单 */}
          <Menu
            anchorEl={exportAnchorEl}
            open={exportMenuOpen}
            onClose={() => setExportAnchorEl(null)}
            anchorOrigin={{
              vertical: 'bottom',
              horizontal: 'right',
            }}
            transformOrigin={{
              vertical: 'top',
              horizontal: 'right',
            }}
          >
            <MenuItem onClick={handleExportTxt} sx={{ gap: 1 }}>
              <DescriptionIcon fontSize="small" />
              导出为 TXT
            </MenuItem>
            <MenuItem onClick={handleExportDocx} sx={{ gap: 1 }}>
              <ArticleIcon fontSize="small" />
              导出为 DOCX
            </MenuItem>
          </Menu>

          {/* 保存按钮 */}
          <Button
            variant="contained"
            color="primary"
            startIcon={<SaveIcon />}
            onClick={handleSave}
            disabled={!isDirty || isSaving}
          >
            保存
          </Button>

          {/* 切换推荐面板 */}
          <IconButton
            onClick={() => setShowRecommendations(!showRecommendations)}
            color="primary"
            size="small"
          >
            {showRecommendations ? <ChevronRightIcon /> : <ChevronLeftIcon />}
          </IconButton>
        </Box>
      </Box>

      <Grid container spacing={2}>
        {/* 左侧：编辑器 */}
        <Grid item xs={12} md={showRecommendations ? 8 : 12}>
          <TextField
            fullWidth
            multiline
            rows={20}
            value={content}
            onChange={(e) => dispatch(setContent(e.target.value))}
            placeholder="在这里开始编写你的章节..."
            variant="outlined"
            inputRef={contentRef}
            sx={{
              '& .MuiOutlinedInput-root': {
                fontFamily: 'Fira Code, monospace',
                fontSize: '14px',
              },
            }}
          />

          <Box sx={{ mt: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Box sx={{ display: 'flex', gap: 3 }}>
              <Typography variant="body2" color="text.secondary">
                📝 字数: <strong>{wordCount}</strong>
              </Typography>
              <Typography variant="body2" color="text.secondary">
                📄 字符: <strong>{charCount}</strong>
              </Typography>
            </Box>
            <Typography variant="caption" color="info.main">
              ℹ️ 自动保存间隔: 60秒 | 手动保存: Ctrl+S
            </Typography>
          </Box>
        </Grid>

        {/* 右侧：推荐设定 */}
        {showRecommendations && (
          <Grid item xs={12} md={4}>
            <Paper elevation={2} sx={{ p: 2, height: 'calc(100vh - 250px)', overflow: 'auto' }}>
              <SettingRecommendations
                projectId={Number(projectId)}
                limit={10}
                showInsertButton={true}
                onInsertItem={(item) => handleInsertSetting(item.name)}
                title="推荐设定"
              />
            </Paper>
          </Grid>
        )}
      </Grid>



      {/* 保存成功提示 */}
      <Snackbar
        open={!!saveMessage}
        autoHideDuration={3000}
        onClose={() => setSaveMessage('')}
      >
        <Alert severity="success">{saveMessage}</Alert>
      </Snackbar>

      {/* 保存失败提示 */}
      <Snackbar
        open={!!saveError}
        autoHideDuration={3000}
        onClose={() => setSaveError('')}
      >
        <Alert severity="error">{saveError}</Alert>
      </Snackbar>

      {/* 自动保存提示 */}
      <Snackbar
        open={isSaving}
        autoHideDuration={2000}
        onClose={() => {}}
      >
        <Alert severity="info">自动保存中...</Alert>
      </Snackbar>

      {/* 版本历史对话框 */}
      <Dialog
        open={historyDialogOpen}
        onClose={() => setHistoryDialogOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2,
            boxShadow: 24,
          }
        }}
      >
        <DialogTitle sx={{
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          pb: 2
        }}>
          <HistoryIcon color="primary" />
          版本历史
          {revisions.length > 0 && (
            <Typography variant="caption" color="text.secondary">
              (共 {revisions.length} 个版本)
            </Typography>
          )}
        </DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          {loadingRevisions ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : revisions.length === 0 ? (
            <Box sx={{
              py: 6,
              textAlign: 'center',
              color: 'text.secondary'
            }}>
              <HistoryIcon sx={{ fontSize: 64, opacity: 0.3, mb: 2 }} />
              <Typography variant="body1">
                暂无版本历史
              </Typography>
              <Typography variant="caption">
                修改章节内容后会自动创建版本快照
              </Typography>
            </Box>
          ) : (
            <List sx={{ p: 0 }}>
              {revisions.map((revision, index) => (
                <div key={revision.id}>
                  <ListItem
                    sx={{
                      py: 2,
                      '&:hover': {
                        bgcolor: 'action.hover',
                      },
                    }}
                    secondaryAction={
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<RestoreIcon />}
                        onClick={() => handleOpenRestoreConfirm(revision)}
                        sx={{
                          minWidth: 80,
                        }}
                      >
                        恢复
                      </Button>
                    }
                  >
                    <ListItemText
                      primary={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                          <Typography variant="body1" fontWeight={500}>
                            {revision.revision_note || '自动保存'}
                          </Typography>
                          <Box
                            sx={{
                              px: 1,
                              py: 0.25,
                              bgcolor: 'primary.main',
                              color: 'white',
                              borderRadius: 1,
                              fontSize: '0.75rem'
                            }}
                          >
                            {revision.word_count} 字
                          </Box>
                        </Box>
                      }
                      secondary={
                        <Typography variant="caption" color="text.secondary">
                          🕒 {new Date(revision.created_at).toLocaleString('zh-CN', {
                            year: 'numeric',
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                          })}
                        </Typography>
                      }
                    />
                  </ListItem>
                  {index < revisions.length - 1 && <Divider />}
                </div>

              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions sx={{ borderTop: 1, borderColor: 'divider', pt: 2 }}>
          <Button onClick={() => setHistoryDialogOpen(false)} variant="outlined">
            关闭
          </Button>
        </DialogActions>
      </Dialog>

      {/* 章节逻辑检查结果对话框 */}
      <Dialog
        open={logicCheckDialogOpen}
        onClose={() => setLogicCheckDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <WarningIcon color={logicCheckResult?.has_issues ? 'warning' : 'success'} />
          章节逻辑检查结果
        </DialogTitle>
        <DialogContent dividers>
          {!logicCheckResult && (
            <Box sx={{ py: 3 }}>
              <Typography variant="body2" color="text.secondary">
                暂无检查结果，请先点击顶部的「逻辑检查」按钮。
              </Typography>
            </Box>
          )}

          {logicCheckResult && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Box sx={{ p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
                <Typography variant="subtitle1" gutterBottom>
                  总体评估
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {logicCheckResult.summary || (logicCheckResult.has_issues ? '发现了一些逻辑问题，请参考下方列表。' : '未发现明显逻辑问题。')}
                </Typography>
              </Box>

              {!logicCheckResult.has_issues && (
                <Box sx={{ p: 2, bgcolor: 'success.light', borderRadius: 1 }}>
                  <Typography variant="body2" color="success.contrastText">
                    ✅ 未发现角色功法使用或境界相关的逻辑问题。
                  </Typography>
                </Box>
              )}

              {logicCheckResult.has_issues && Array.isArray(logicCheckResult.issues) && logicCheckResult.issues.length > 0 && (
                <Box>
                  <Typography variant="subtitle1" gutterBottom>
                    发现的问题（共 {logicCheckResult.issues.length} 条）
                  </Typography>
                  <List sx={{ maxHeight: 360, overflow: 'auto' }}>
                    {logicCheckResult.issues.map((issue: any, index: number) => (
                      <Box key={index} sx={{ mb: 1 }}>
                        <ListItem alignItems="flex-start">
                          <ListItemText
                            primary={
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Typography variant="body1" fontWeight={500}>
                                  {issue.character_name || '未知角色'} 使用 {issue.technique_name || '未知功法'}
                                </Typography>
                                <Typography
                                  variant="caption"
                                  sx={{
                                    px: 1,
                                    py: 0.25,
                                    borderRadius: 1,
                                    bgcolor: issue.issue_type === '境界不足' ? 'error.light' : 'warning.light',
                                    color: 'text.primary',
                                  }}
                                >
                                  {issue.issue_type || '逻辑问题'}
                                </Typography>
                              </Box>
                            }
                            secondary={
                              <Box sx={{ mt: 0.5 }}>
                                <Typography variant="body2" color="text.secondary">
                                  {issue.description}
                                </Typography>
                                {issue.suggestion && (
                                  <Typography variant="body2" color="primary.main" sx={{ mt: 0.5 }}>
                                    建议：{issue.suggestion}
                                  </Typography>
                                )}
                              </Box>
                            }
                          />
                        </ListItem>
                        {index < logicCheckResult.issues.length - 1 && <Divider />}
                      </Box>
                    ))}
                  </List>
                </Box>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLogicCheckDialogOpen(false)}>关闭</Button>
        </DialogActions>
      </Dialog>


      {/* 确认恢复对话框 */}
      <Dialog
        open={confirmDialogOpen}
        onClose={() => !restoringRevision && setConfirmDialogOpen(false)}
        maxWidth="sm"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2,
          }
        }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <WarningIcon color="warning" />
          确认恢复版本
        </DialogTitle>
        <DialogContent>
          <Typography variant="body1" gutterBottom>
            确定要恢夏到这个版本吗？
          </Typography>
          {selectedRevision && (
            <Box sx={{
              mt: 2,
              p: 2,
              bgcolor: 'action.hover',
              borderRadius: 1,
              borderLeft: 4,
              borderColor: 'primary.main'
            }}>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                <strong>版本信息：</strong>
              </Typography>
              <Typography variant="body2">
                • 备注：{selectedRevision.revision_note || '自动保存'}
              </Typography>
              <Typography variant="body2">
                • 字数：{selectedRevision.word_count} 字
              </Typography>
              <Typography variant="body2">
                • 时间：{new Date(selectedRevision.created_at).toLocaleString('zh-CN')}
              </Typography>
            </Box>
          )}
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            ⚠️ 当前的内容将被自动备份为新版本，不会丢失。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setConfirmDialogOpen(false)}
            disabled={restoringRevision}
          >
            取消
          </Button>
          <Button
            onClick={handleConfirmRestore}
            variant="contained"
            color="primary"
            disabled={restoringRevision}
            startIcon={restoringRevision ? <CircularProgress size={16} /> : <RestoreIcon />}
          >
            {restoringRevision ? '恢复中...' : '确认恢复'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 🆕 再次优化对话框 */}
      <Dialog
        open={optimizeDialogOpen}
        onClose={() => !optimizing && setOptimizeDialogOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2,
          }
        }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          ✨ 再次优化章节
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            AI 将自动分析当前章节并提出优化建议。您可以补充额外的优化意见，或者直接点击「开始优化」依赖系统自动评审。
          </Typography>

          <TextField
            fullWidth
            multiline
            rows={6}
            value={userFeedback}
            onChange={(e) => setUserFeedback(e.target.value)}
            placeholder={`请输入您的优化意见（可选）

例如：
- 增加更多情感描写
- 加强动作场面的紧张感
- 修改某个人物的对话语气...`}
            variant="outlined"
            sx={{
              mt: 2,
              '& .MuiOutlinedInput-root': {
                fontFamily: 'inherit',
                fontSize: '14px',
              },
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setOptimizeDialogOpen(false)}
            disabled={optimizing}
          >
            取消
          </Button>
          <Button
            onClick={handleConfirmOptimize}
            variant="contained"
            color="secondary"
            disabled={optimizing}
            startIcon={optimizing ? <CircularProgress size={16} /> : undefined}
          >
            {optimizing ? '优化中...' : '开始优化'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 🆕 重新生成章节对话框 */}
      <Dialog
        open={regenerateDialogOpen}
        onClose={() => !regenerating && setRegenerateDialogOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2,
          }
        }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <WarningIcon color="error" />
          重新生成章节
        </DialogTitle>
        <DialogContent>
          <Box sx={{ mb: 2, p: 2, bgcolor: 'error.light', borderRadius: 1 }}>
            <Typography variant="body2" color="error.contrastText">
              ⚠️ 警告：重新生成将完全重写当前章节内容，原有内容将被覆盖！
            </Typography>
          </Box>

          <Typography variant="body2" color="text.secondary" gutterBottom>
            AI 将根据项目设定和章节大纲，完全重新创作本章节内容。请说明重新生成的理由，帮助AI更好地理解您的需求。
          </Typography>

          <TextField
            fullWidth
            multiline
            rows={6}
            value={regenerateReason}
            onChange={(e) => setRegenerateReason(e.target.value)}
            placeholder={`请输入重新生成的理由（可选）

例如：
- 当前章节质量不理想，希望完全重写
- 想要改变章节的叙事风格
- 需要调整情节走向...`}
            variant="outlined"
            sx={{
              mt: 2,
              '& .MuiOutlinedInput-root': {
                fontFamily: 'inherit',
                fontSize: '14px',
              },
            }}
          />

          <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
            💡 提示：当前内容将被自动备份为版本历史，您可以通过「版本历史」功能恢复。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setRegenerateDialogOpen(false)}
            disabled={regenerating}
          >
            取消
          </Button>
          <Button
            onClick={handleConfirmRegenerate}
            variant="contained"
            color="error"
            disabled={regenerating}
            startIcon={regenerating ? <CircularProgress size={16} /> : undefined}
          >
            {regenerating ? '生成中...' : '确认重新生成'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  )
}

