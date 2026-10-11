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
import { useFormats } from '@/i18n'
import { apiClient } from '@/services/api'
import SettingRecommendations from '@/components/SettingRecommendations'
import { useTranslation } from 'react-i18next'

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  window.URL.revokeObjectURL(url)
}


export default function EditorPage() {
  // 自动保存与版本历史都要看到秒：同一分钟内的多次保存，少了秒就分不清先后。
  const { t } = useTranslation()
  const { formatDateTimeWithSeconds, formatTimeWithSeconds } = useFormats()
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
        setSaveMessage(t('chapterEditor.msg.savingHint'))
        
        await dispatch(updateChapter({
          chapterId: parseInt(chapterId),
          data: { content },
        }))
        dispatch(clearDirty())
        setLastSaved(new Date()) // 🆕 设置最后保存时间
        
        // 🆕 显示成功信息，说明AI分析在后台进行
        setSaveMessage(t('chapterEditor.msg.savedHint'))
        setTimeout(() => setSaveMessage(''), 5000) // 5秒后清除提示
      } catch (error) {
        setSaveError(t('chapterEditor.msg.saveFailed'))
        setTimeout(() => setSaveError(''), 3000)
      }
    }
  }

  // 打开版本历史对话框
  const handleOpenHistory = async () => {
    setHistoryDialogOpen(true)
    setLoadingRevisions(true)
    try {
      const response = await apiClient.get(`/api/v1/chapters/${chapterId}/revisions`)
      setRevisions(response.data)
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
      const response = await apiClient.post('/api/v1/workflow/optimize-chapter', {
        project_id: parseInt(projectId),
        chapter_id: parseInt(chapterId),
        current_content: content,
        user_feedback: feedback,
      })
      const data = response.data
      setSaveMessage(t('chapterEditor.msg.optimizeSubmitted'))

      // 轮询任务状态
      pollOptimizeTaskStatus(data.task_id)
    } catch (error: any) {
      setSaveError(error.message || t('chapterEditor.msg.optimizeFailed'))
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
      const response = await apiClient.post('/api/v1/workflow/regenerate-chapter', {
        project_id: parseInt(projectId),
        chapter_id: parseInt(chapterId),
        reason,
        user_feedback: reason,
      })
      const data = response.data
      setSaveMessage(t('chapterEditor.msg.regenerateSubmitted'))

      // 轮询任务状态
      pollRegenerateTaskStatus(data.task_id)
    } catch (error: any) {
      setSaveError(error.message || t('chapterEditor.msg.regenerateFailed'))
      setRegenerating(false)
    }
  }

  // 轮询重新生成任务状态
  const pollRegenerateTaskStatus = async (taskId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await apiClient.getWorkflowTaskStatus(taskId)

        if (response.status < 200 || response.status >= 300) {
          clearInterval(pollInterval)
          setRegenerating(false)
          setSaveError(t('chapterEditor.msg.taskStatusFailed'))
          return
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
        setSaveError(t('chapterEditor.msg.regenerateTimeout'))
      }
    }, 600000)
  }

  // 轮询优化任务状态
  const pollOptimizeTaskStatus = async (taskId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await apiClient.getWorkflowTaskStatus(taskId)

        if (response.status < 200 || response.status >= 300) {
          clearInterval(pollInterval)
          setOptimizing(false)
          setSaveError(t('chapterEditor.msg.taskStatusFailed'))
          return
        }

        const data = response.data
        
        if (data.status === 'completed') {
          clearInterval(pollInterval)
          
          // 解析结果（result 是 JSON 字符串）
          try {
            const result = typeof data.result === 'string' ? JSON.parse(data.result) : data.result
            
            if (result && result.optimized_content) {
              dispatch(setContent(result.optimized_content))
              setSaveMessage(t('chapterEditor.msg.optimizeDone', { score: result.original_score || 'N/A' }))
            } else {
              setSaveError(t('chapterEditor.msg.optimizeEmpty'))
            }
          } catch {
            setSaveError(t('chapterEditor.msg.optimizeParseFailed'))
          }
          
          setOptimizing(false)
        } else if (data.status === 'failed') {
          clearInterval(pollInterval)
          setSaveError(t('chapterEditor.msg.optimizeFailedDetail', { error: data.error || t('chapterEditor.msg.unknownError') }))
          setOptimizing(false)
        } else if (data.status === 'running') {
          // 更新进度提示
          setSaveMessage(t('chapterEditor.msg.optimizingProgress', { progress: data.progress || 50 }))
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
        setSaveError(t('chapterEditor.msg.optimizeTimeout'))
      }
    }, 300000)
  }

  // 运行章节逻辑检查
  const handleCheckLogic = async () => {
    if (!chapterId || !projectId) return
    setCheckingLogic(true)
    try {
      const response = await apiClient.post('/api/v1/ai/check-chapter-logic', {
        chapter_id: parseInt(chapterId),
        project_id: parseInt(projectId),
      })
      setLogicCheckResult(response.data)
      setLogicCheckDialogOpen(true)
    } catch {
      setSaveError(t('chapterEditor.msg.logicCheckApiFailed'))
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
      const response = await apiClient.post(`/api/v1/chapters/${chapterId}/revisions/${selectedRevision.id}/restore`)
      const chapter = response.data
      dispatch(setContent(chapter.content))
      dispatch(clearDirty())
      setSaveMessage(t('chapterEditor.msg.restoreDone'))
      setConfirmDialogOpen(false)
      setHistoryDialogOpen(false)
      // 重新加载版本历史
      setTimeout(() => handleOpenHistory(), 500)
    } catch {
      setSaveError(t('chapterEditor.msg.restoreFailed'))
    } finally {
      setRestoringRevision(false)
    }
  }

  // 导出TXT
  const handleExportTxt = async () => {
    setExportAnchorEl(null)
    setExporting(true)
    try {
      const response = await apiClient.get(`/api/v1/chapters/${chapterId}/export/txt`, {
        responseType: 'blob',
      })
      triggerBlobDownload(response.data as Blob, `${currentChapter?.title || t('chapterEditor.msg.fileNameFallback')}.txt`)
      setSaveMessage(t('chapterEditor.msg.exportTxtDone'))
    } catch {
      setSaveError(t('chapterEditor.msg.exportTxtFailed'))
    } finally {
      setExporting(false)
    }
  }

  // 导出DOCX
  const handleExportDocx = async () => {
    setExportAnchorEl(null)
    setExporting(true)
    try {
      const response = await apiClient.get(`/api/v1/chapters/${chapterId}/export/docx`, {
        responseType: 'blob',
      })
      triggerBlobDownload(response.data as Blob, `${currentChapter?.title || t('chapterEditor.msg.fileNameFallback')}.docx`)
      setSaveMessage(t('chapterEditor.msg.exportDocxDone'))
    } catch {
      setSaveError(t('chapterEditor.msg.exportDocxFailed'))
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
            {t('action.back')}
          </Button>
          <Typography variant="h5">
            {currentChapter?.title || t('chapterEditor.page.titleFallback')}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
          {/* 🆕 显示最后保存时间 */}
          {lastSaved && (
            <Typography variant="caption" color="text.secondary">
              {t('chapterEditor.page.lastSaved', { time: formatTimeWithSeconds(lastSaved) })}
            </Typography>
          )}
          {isDirty && <Typography variant="caption" color="warning.main">{t('chapterEditor.page.unsavedChanges')}</Typography>}
          {isSaving && <CircularProgress size={24} />}

          {/* 版本历史按钮 */}
          <Button
            variant="outlined"
            startIcon={<HistoryIcon />}
            onClick={handleOpenHistory}
            size="small"
          >
            {t('chapterEditor.page.history')}
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
            {optimizing ? t('chapterEditor.page.optimizing') : t('chapterEditor.page.reOptimize')}
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
            {regenerating ? t('chapterEditor.page.generating') : t('chapterEditor.page.regenerate')}
          </Button>

          {/* 章节逻辑检查按钮 */}
          <Button
            variant="outlined"
            size="small"
            onClick={handleCheckLogic}
            disabled={checkingLogic}
            startIcon={checkingLogic ? <CircularProgress size={16} /> : undefined}
          >
            {checkingLogic ? t('chapterEditor.page.checking') : t('chapterEditor.page.logicCheck')}
          </Button>

          {/* 导出按钮 */}
          <Button
            variant="outlined"
            startIcon={exporting ? <CircularProgress size={16} /> : <FileDownloadIcon />}
            onClick={(e) => setExportAnchorEl(e.currentTarget)}
            size="small"
            disabled={exporting}
          >
            {exporting ? t('chapterEditor.page.exporting') : t('chapterEditor.page.export')}
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
              {t('chapterEditor.page.exportTxt')}
            </MenuItem>
            <MenuItem onClick={handleExportDocx} sx={{ gap: 1 }}>
              <ArticleIcon fontSize="small" />
              {t('chapterEditor.page.exportDocx')}
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
            {t('common.save')}
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
            placeholder={t('chapterEditor.page.editorPlaceholder')}
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
                {t('chapterEditor.page.wordCountLabel')}<strong>{wordCount}</strong>
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('chapterEditor.page.charCountLabel')}<strong>{charCount}</strong>
              </Typography>
            </Box>
            <Typography variant="caption" color="info.main">
              {t('chapterEditor.page.autoSaveHint', { seconds: 60 })}
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
                title={t('chapterEditor.page.recommendTitle')}
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
        <Alert severity="info">{t('chapterEditor.msg.autoSaving')}</Alert>
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
          {t('chapterEditor.page.history')}
          {revisions.length > 0 && (
            <Typography variant="caption" color="text.secondary">
              {t('chapterEditor.history.count', { count: revisions.length })}
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
                {t('chapterEditor.history.empty')}
              </Typography>
              <Typography variant="caption">
                {t('chapterEditor.history.emptyHint')}
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
                        {t('chapterEditor.history.restore')}
                      </Button>
                    }
                  >
                    <ListItemText
                      primary={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                          <Typography variant="body1" fontWeight={500}>
                            {revision.revision_note || t('chapterEditor.history.autoSaveNote')}
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
                            {t('chapterEditor.history.words', { count: revision.word_count })}
                          </Box>
                        </Box>
                      }
                      secondary={
                        <Typography variant="caption" color="text.secondary">
                          🕒 {formatDateTimeWithSeconds(revision.created_at)}
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
            {t('common.close')}
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
          {t('chapterEditor.logicCheck.title')}
        </DialogTitle>
        <DialogContent dividers>
          {!logicCheckResult && (
            <Box sx={{ py: 3 }}>
              <Typography variant="body2" color="text.secondary">
                {t('chapterEditor.logicCheck.emptyHint')}
              </Typography>
            </Box>
          )}

          {logicCheckResult && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Box sx={{ p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
                <Typography variant="subtitle1" gutterBottom>
                  {t('chapterEditor.logicCheck.overall')}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {logicCheckResult.summary || (logicCheckResult.has_issues ? t('chapterEditor.logicCheck.summaryIssues') : t('chapterEditor.logicCheck.summaryClean'))}
                </Typography>
              </Box>

              {!logicCheckResult.has_issues && (
                <Box sx={{ p: 2, bgcolor: 'success.light', borderRadius: 1 }}>
                  <Typography variant="body2" color="success.contrastText">
                    {t('chapterEditor.logicCheck.cleanBanner')}
                  </Typography>
                </Box>
              )}

              {logicCheckResult.has_issues && Array.isArray(logicCheckResult.issues) && logicCheckResult.issues.length > 0 && (
                <Box>
                  <Typography variant="subtitle1" gutterBottom>
                    {t('chapterEditor.logicCheck.issuesHead', { count: logicCheckResult.issues.length })}
                  </Typography>
                  <List sx={{ maxHeight: 360, overflow: 'auto' }}>
                    {logicCheckResult.issues.map((issue: any, index: number) => (
                      <Box key={index} sx={{ mb: 1 }}>
                        <ListItem alignItems="flex-start">
                          <ListItemText
                            primary={
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Typography variant="body1" fontWeight={500}>
                                  {issue.character_name || t('chapterEditor.logicCheck.unknownCharacter')} {t('chapterEditor.logicCheck.uses')} {issue.technique_name || t('chapterEditor.logicCheck.unknownTechnique')}
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
                                  {issue.issue_type || t('chapterEditor.logicCheck.issueFallback')}
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
                                    {t('chapterEditor.logicCheck.suggestionPrefix')}{issue.suggestion}
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
          <Button onClick={() => setLogicCheckDialogOpen(false)}>{t('common.close')}</Button>
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
          {t('chapterEditor.restore.title')}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body1" gutterBottom>
            {t('chapterEditor.restore.confirmQuestion')}
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
                <strong>{t('chapterEditor.restore.versionInfo')}</strong>
              </Typography>
              <Typography variant="body2">
                {t('chapterEditor.restore.notePrefix')}{selectedRevision.revision_note || t('chapterEditor.restore.noteFallback')}
              </Typography>
              <Typography variant="body2">
                {t('chapterEditor.restore.wordCountPrefix')}{selectedRevision.word_count}{t('chapterEditor.restore.wordCountSuffix')}
              </Typography>
              <Typography variant="body2">
                {t('chapterEditor.restore.timePrefix')}{formatDateTimeWithSeconds(selectedRevision.created_at)}
              </Typography>
            </Box>
          )}
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            {t('chapterEditor.restore.backupWarning')}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setConfirmDialogOpen(false)}
            disabled={restoringRevision}
          >
            {t('common.cancel')}
          </Button>
          <Button
            onClick={handleConfirmRestore}
            variant="contained"
            color="primary"
            disabled={restoringRevision}
            startIcon={restoringRevision ? <CircularProgress size={16} /> : <RestoreIcon />}
          >
            {restoringRevision ? t('chapterEditor.restore.restoring') : t('chapterEditor.restore.confirm')}
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
          {t('chapterEditor.optimize.title')}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            {t('chapterEditor.optimize.desc')}
          </Typography>

          <TextField
            fullWidth
            multiline
            rows={6}
            value={userFeedback}
            onChange={(e) => setUserFeedback(e.target.value)}
            placeholder={t('chapterEditor.optimize.placeholder')}
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
            {t('common.cancel')}
          </Button>
          <Button
            onClick={handleConfirmOptimize}
            variant="contained"
            color="secondary"
            disabled={optimizing}
            startIcon={optimizing ? <CircularProgress size={16} /> : undefined}
          >
            {optimizing ? t('chapterEditor.optimize.running') : t('chapterEditor.optimize.start')}
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
          {t('chapterEditor.regenerate.title')}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ mb: 2, p: 2, bgcolor: 'error.light', borderRadius: 1 }}>
            <Typography variant="body2" color="error.contrastText">
              {t('chapterEditor.regenerate.warning')}
            </Typography>
          </Box>

          <Typography variant="body2" color="text.secondary" gutterBottom>
            {t('chapterEditor.regenerate.desc')}
          </Typography>

          <TextField
            fullWidth
            multiline
            rows={6}
            value={regenerateReason}
            onChange={(e) => setRegenerateReason(e.target.value)}
            placeholder={t('chapterEditor.regenerate.placeholder')}
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
            {t('chapterEditor.regenerate.backupHint')}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setRegenerateDialogOpen(false)}
            disabled={regenerating}
          >
            {t('common.cancel')}
          </Button>
          <Button
            onClick={handleConfirmRegenerate}
            variant="contained"
            color="error"
            disabled={regenerating}
            startIcon={regenerating ? <CircularProgress size={16} /> : undefined}
          >
            {regenerating ? t('chapterEditor.regenerate.generating') : t('chapterEditor.regenerate.confirm')}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  )
}

