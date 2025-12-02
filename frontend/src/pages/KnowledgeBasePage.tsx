import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Container,
  Box,
  Tabs,
  Tab,
  Button,
  Typography,
  CircularProgress,
  Alert,
  Snackbar,
  Paper,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import SaveIcon from '@mui/icons-material/Save'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { logger } from '@/utils/logger'
import MarkdownRenderer from '@/components/MarkdownRenderer'
import VditorEditor from '@/components/VditorEditor'

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  )
}

export default function KnowledgeBasePage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const [tabValue, setTabValue] = useState(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 工作流数据
  const [worldSetting, setWorldSetting] = useState('')
  const [characters, setCharacters] = useState('')
  const [plotOutline, setPlotOutline] = useState('')

  // 编辑状态
  const [isEditing, setIsEditing] = useState(false)
  const [editedContent, setEditedContent] = useState('')

  // 提示消息
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')

  // 页面加载时获取数据
  useEffect(() => {
    loadWorkflowData()
  }, [projectId])

  // 加载工作流数据
  const loadWorkflowData = async () => {
    if (!projectId) return

    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        logger.log('✅ 加载工作流数据:', data)

        // 解析数据
        const stages = data.stages || {}
        setWorldSetting(parseContent(stages.world_setting))
        setCharacters(parseContent(stages.characters))
        setPlotOutline(parseContent(stages.plot_outline))
      } else {
        const errorData = await response.json()
        setError(errorData.detail || '加载失败')
      }
    } catch (err) {
      logger.error('❌ 加载工作流数据失败:', err)
      setError('加载失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  // 解析内容（可能是 JSON 字符串）
  const parseContent = (content: any): string => {
    if (!content) return ''
    if (typeof content === 'string') {
      // 尝试解析 JSON 字符串
      try {
        if (content.startsWith('"') || content.startsWith('[')) {
          const parsed = JSON.parse(content)
          if (Array.isArray(parsed)) {
            return parsed.map(item =>
              typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)
            ).join('\n\n')
          }
          return String(parsed)
        }
      } catch {
        // 解析失败，返回原始字符串
      }
      return content
    }
    if (Array.isArray(content)) {
      return content.map(item =>
        typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)
      ).join('\n\n')
    }
    if (typeof content === 'object') {
      return JSON.stringify(content, null, 2)
    }
    return String(content)
  }

  // 获取当前 Tab 对应的内容
  const getCurrentContent = (): string => {
    switch (tabValue) {
      case 0: return worldSetting
      case 1: return characters
      case 2: return plotOutline
      default: return ''
    }
  }

  // 获取当前 Tab 对应的阶段名称
  const getCurrentStage = (): string => {
    switch (tabValue) {
      case 0: return 'world_builder'
      case 1: return 'character_designer'
      case 2: return 'structure'
      default: return ''
    }
  }

  // 开始编辑
  const handleStartEdit = () => {
    setEditedContent(getCurrentContent())
    setIsEditing(true)
  }

  // 取消编辑
  const handleCancelEdit = () => {
    setIsEditing(false)
    setEditedContent('')
  }

  // 保存编辑
  const handleSaveEdit = async () => {
    if (!projectId) return

    setSaving(true)

    try {
      const stage = getCurrentStage()
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/${stage}/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // 更新本地状态
        switch (tabValue) {
          case 0: setWorldSetting(editedContent); break
          case 1: setCharacters(editedContent); break
          case 2: setPlotOutline(editedContent); break
        }

        setIsEditing(false)
        setSnackbarMessage('✅ 保存成功')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
      } else {
        const errorData = await response.json()
        setSnackbarMessage(errorData.detail || '保存失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (err) {
      logger.error('❌ 保存失败:', err)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setSaving(false)
    }
  }

  // 获取 Tab 标题
  const getTabTitle = (): string => {
    switch (tabValue) {
      case 0: return '世界观设定'
      case 1: return '人物设定'
      case 2: return '剧情大纲'
      default: return ''
    }
  }

  // 切换 Tab 时取消编辑状态
  const handleTabChange = (_e: React.SyntheticEvent, newValue: number) => {
    if (isEditing) {
      setIsEditing(false)
      setEditedContent('')
    }
    setTabValue(newValue)
  }

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      {/* 页面标题栏 */}
      <Box sx={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        mb: 3,
        pb: 2,
        borderBottom: '2px solid',
        borderColor: 'primary.light'
      }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/dashboard')}
          sx={{ fontWeight: 500 }}
        >
          ← 返回
        </Button>
        <Typography variant="h5" sx={{
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 1
        }}>
          📚 知识库
        </Typography>
      </Box>

      {/* 加载状态 */}
      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress />
        </Box>
      )}

      {/* 错误提示 */}
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
          <Button size="small" onClick={loadWorkflowData} sx={{ ml: 2 }}>
            重试
          </Button>
        </Alert>
      )}

      {/* 主内容 */}
      {!loading && !error && (
        <>
          {/* 标签页导航 */}
          <Box sx={{
            borderBottom: 1,
            borderColor: 'divider',
            mb: 2,
            bgcolor: 'grey.50',
            borderRadius: '8px 8px 0 0'
          }}>
            <Tabs
              value={tabValue}
              onChange={handleTabChange}
              sx={{
                '& .MuiTab-root': {
                  fontWeight: 500,
                  fontSize: '0.95rem',
                  minHeight: 56,
                }
              }}
            >
              <Tab
                icon={<span style={{ marginRight: 8 }}>🌍</span>}
                iconPosition="start"
                label="世界观设定"
              />
              <Tab
                icon={<span style={{ marginRight: 8 }}>👥</span>}
                iconPosition="start"
                label="人物设定"
              />
              <Tab
                icon={<span style={{ marginRight: 8 }}>📋</span>}
                iconPosition="start"
                label="剧情大纲"
              />
            </Tabs>
          </Box>

          {/* 提示信息 */}
          <Alert severity="info" sx={{ mb: 3 }}>
            📖 此页面展示工作流生成的设定数据，编辑后将同步到工作流中
          </Alert>

          {/* 操作按钮 */}
          <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
            {!isEditing ? (
              <Button
                variant="contained"
                startIcon={<EditIcon />}
                onClick={handleStartEdit}
                disabled={!getCurrentContent()}
                sx={{ borderRadius: 2 }}
              >
                编辑{getTabTitle()}
              </Button>
            ) : (
              <>
                <Button
                  variant="contained"
                  color="primary"
                  startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
                  onClick={handleSaveEdit}
                  disabled={saving}
                  sx={{ borderRadius: 2 }}
                >
                  {saving ? '保存中...' : '保存'}
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleCancelEdit}
                  disabled={saving}
                  sx={{ borderRadius: 2 }}
                >
                  取消
                </Button>
              </>
            )}
          </Box>

          {/* 内容展示区域 */}
          <TabPanel value={tabValue} index={0}>
            {isEditing ? (
              <VditorEditor
                value={editedContent}
                onChange={(val) => setEditedContent(val)}
                placeholder="世界观设定内容（支持 Markdown 格式）..."
                height={500}
              />
            ) : (
              <Paper
                elevation={0}
                sx={{
                  bgcolor: 'background.paper',
                  p: 4,
                  borderRadius: 2,
                  minHeight: 400,
                  border: '1px solid',
                  borderColor: 'grey.200',
                }}
              >
                {worldSetting ? (
                  <MarkdownRenderer content={worldSetting} />
                ) : (
                  <Typography color="text.secondary" sx={{ textAlign: 'center', py: 8 }}>
                    📭 暂无世界观设定，请先在工作流中生成
                  </Typography>
                )}
              </Paper>
            )}
          </TabPanel>

          <TabPanel value={tabValue} index={1}>
            {isEditing ? (
              <VditorEditor
                value={editedContent}
                onChange={(val) => setEditedContent(val)}
                placeholder="人物设定内容（支持 Markdown 格式）..."
                height={500}
              />
            ) : (
              <Paper
                elevation={0}
                sx={{
                  bgcolor: 'background.paper',
                  p: 4,
                  borderRadius: 2,
                  minHeight: 400,
                  border: '1px solid',
                  borderColor: 'grey.200',
                }}
              >
                {characters ? (
                  <MarkdownRenderer content={characters} />
                ) : (
                  <Typography color="text.secondary" sx={{ textAlign: 'center', py: 8 }}>
                    📭 暂无人物设定，请先在工作流中生成
                  </Typography>
                )}
              </Paper>
            )}
          </TabPanel>

          <TabPanel value={tabValue} index={2}>
            {isEditing ? (
              <VditorEditor
                value={editedContent}
                onChange={(val) => setEditedContent(val)}
                placeholder="剧情大纲内容（支持 Markdown 格式）..."
                height={500}
              />
            ) : (
              <Paper
                elevation={0}
                sx={{
                  bgcolor: 'background.paper',
                  p: 4,
                  borderRadius: 2,
                  minHeight: 400,
                  border: '1px solid',
                  borderColor: 'grey.200',
                }}
              >
                {plotOutline ? (
                  <MarkdownRenderer content={plotOutline} />
                ) : (
                  <Typography color="text.secondary" sx={{ textAlign: 'center', py: 8 }}>
                    📭 暂无剧情大纲，请先在工作流中生成
                  </Typography>
                )}
              </Paper>
            )}
          </TabPanel>
        </>
      )}

      {/* 提示消息 */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={3000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert severity={snackbarSeverity} onClose={() => setSnackbarOpen(false)}>
          {snackbarMessage}
        </Alert>
      </Snackbar>
    </Container>
  )
}

