/**
 * 拆书工具页面
 * 
 * 功能：
 * 1. 上传书籍文本/文件
 * 2. 执行章节切分
 * 3. AI内容分析
 * 4. 查看分析结果
 * 5. 导入为工作流项目
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Box,
  Container,
  Typography,
  Paper,
  Button,
  TextField,
  Tabs,
  Tab,
  CircularProgress,
  LinearProgress,
  Alert,
  Card,
  CardContent,
  CardActions,
  Grid,
  Chip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  List,
  ListItem,
  ListItemText,
  Divider,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Tooltip,
  Checkbox,
  FormControlLabel,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import ArticleIcon from '@mui/icons-material/Article'
import AnalyticsIcon from '@mui/icons-material/Analytics'
import PersonIcon from '@mui/icons-material/Person'
import PublicIcon from '@mui/icons-material/Public'
import TimelineIcon from '@mui/icons-material/Timeline'
import BrushIcon from '@mui/icons-material/Brush'
import DeleteIcon from '@mui/icons-material/Delete'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ImportExportIcon from '@mui/icons-material/ImportExport'

import * as bookParserApi from '@/services/bookParserApi'
import type { BookSource, BookChapter, BookAnalysis, ParseStatus, ImportPreview, ImportRequest } from '@/services/bookParserApi'

// ==================== 子组件 ====================

// 书籍卡片
function BookCard({
  book,
  onSelect,
  onDelete,
}: {
  book: BookSource
  onSelect: () => void
  onDelete: () => void
}) {
  const statusColors: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'error'> = {
    pending: 'default',
    parsing: 'primary',
    chapters_done: 'warning',
    analyzing: 'primary',
    completed: 'success',
    failed: 'error',
  }

  const statusLabels: Record<string, string> = {
    pending: '待解析',
    parsing: '解析中',
    chapters_done: '待分析',
    analyzing: '分析中',
    completed: '已完成',
    failed: '失败',
  }

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
          <Typography variant="h6" noWrap sx={{ maxWidth: '80%' }}>
            {book.title}
          </Typography>
          <Chip
            size="small"
            label={statusLabels[book.status] || book.status}
            color={statusColors[book.status] || 'default'}
          />
        </Box>
        {book.author && (
          <Typography variant="body2" color="text.secondary" gutterBottom>
            作者：{book.author}
          </Typography>
        )}
        <Typography variant="body2" color="text.secondary">
          {book.total_words.toLocaleString()} 字
          {book.total_chapters > 0 && ` · ${book.total_chapters} 章`}
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          {new Date(book.created_at).toLocaleString()}
        </Typography>
      </CardContent>
      <CardActions>
        <Button size="small" onClick={onSelect}>
          查看详情
        </Button>
        <IconButton size="small" color="error" onClick={onDelete}>
          <DeleteIcon fontSize="small" />
        </IconButton>
      </CardActions>
    </Card>
  )
}

// 上传对话框
function UploadDialog({
  open,
  onClose,
  onUpload,
  initialTitle = '',
  initialContent = '',
}: {
  open: boolean
  onClose: () => void
  onUpload: (book: BookSource) => void
  initialTitle?: string
  initialContent?: string
}) {
  const [tabIndex, setTabIndex] = useState(0)
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [content, setContent] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) {
      if (initialTitle) {
        setTitle(initialTitle)
      }
      if (initialContent) {
        setContent(initialContent)
      }
    }
  }, [open, initialTitle, initialContent])

  const handleSubmit = async () => {
    setLoading(true)
    setError('')

    try {
      let book: BookSource
      if (tabIndex === 0) {
        // 粘贴文本
        if (!title.trim() || !content.trim()) {
          setError('请填写书名和内容')
          setLoading(false)
          return
        }
        book = await bookParserApi.uploadText({
          title: title.trim(),
          content: content.trim(),
          author: author.trim() || undefined,
        })
      } else {
        // 上传文件
        if (!file) {
          setError('请选择文件')
          setLoading(false)
          return
        }
        book = await bookParserApi.uploadFile(file, title.trim() || undefined, author.trim() || undefined)
      }

      onUpload(book)
      onClose()
      // 重置表单
      setTitle('')
      setAuthor('')
      setContent('')
      setFile(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '上传失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>上传书籍</DialogTitle>
      <DialogContent>
        <Tabs value={tabIndex} onChange={(_, v) => setTabIndex(v)} sx={{ mb: 2 }}>
          <Tab label="粘贴文本" />
          <Tab label="上传文件" />
        </Tabs>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <TextField
          fullWidth
          label="书名"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          sx={{ mb: 2 }}
        />
        <TextField
          fullWidth
          label="作者（可选）"
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          sx={{ mb: 2 }}
        />

        {tabIndex === 0 ? (
          <TextField
            fullWidth
            multiline
            rows={12}
            label="书籍内容"
            placeholder="将书籍内容粘贴到这里..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        ) : (
          <Box
            sx={{
              border: '2px dashed',
              borderColor: 'divider',
              borderRadius: 2,
              p: 4,
              textAlign: 'center',
              cursor: 'pointer',
              '&:hover': { borderColor: 'primary.main' },
            }}
            onClick={() => document.getElementById('file-input')?.click()}
          >
            <input
              id="file-input"
              type="file"
              accept=".txt"
              hidden
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <CloudUploadIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
            <Typography variant="body1" color="text.secondary">
              {file ? file.name : '点击选择 TXT 文件'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              支持 UTF-8、GBK 编码
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading}>
          取消
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={loading}>
          {loading ? <CircularProgress size={20} /> : '上传'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// 导入对话框
function ImportDialog({
  open,
  onClose,
  preview,
  loading,
  onImport,
}: {
  open: boolean
  onClose: () => void
  preview: ImportPreview | null
  loading: boolean
  onImport: (options: ImportRequest) => void
}) {
  const [projectTitle, setProjectTitle] = useState('')
  const [importSettings, setImportSettings] = useState(true)
  const [importCharacters, setImportCharacters] = useState(true)
  const [importChapters, setImportChapters] = useState(false)  // 🆕 导入章节选项

  const handleImport = () => {
    onImport({
      project_title: projectTitle.trim() || undefined,
      import_settings: importSettings,
      import_characters: importCharacters,
      import_chapters: importChapters,  // 🆕 传递章节导入选项
    })
  }

  if (!preview) return null

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>导入为工作流项目</DialogTitle>
      <DialogContent>
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            将《{preview.book.title}》的分析结果导入为新的工作流项目
          </Typography>
        </Box>

        <TextField
          fullWidth
          label="项目名称"
          placeholder={`${preview.book.title}（续写）`}
          value={projectTitle}
          onChange={(e) => setProjectTitle(e.target.value)}
          sx={{ mb: 2 }}
        />

        <Typography variant="subtitle2" gutterBottom>导入内容</Typography>
        <Box sx={{ ml: 1 }}>
          <FormControlLabel
            control={
              <Checkbox
                checked={importCharacters}
                onChange={(e) => setImportCharacters(e.target.checked)}
                disabled={!preview.import_options.characters}
              />
            }
            label={
              <Box>
                <Typography variant="body2">人物设定</Typography>
                <Typography variant="caption" color="text.secondary">
                  {preview.analyses.find(a => a.type === 'characters')?.item_count || 0} 个人物
                </Typography>
              </Box>
            }
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={importSettings}
                onChange={(e) => setImportSettings(e.target.checked)}
                disabled={!preview.import_options.worldview && !preview.import_options.plot}
              />
            }
            label={
              <Box>
                <Typography variant="body2">世界观、情节设定</Typography>
                <Typography variant="caption" color="text.secondary">
                  {(preview.analyses.find(a => a.type === 'worldview')?.item_count || 0) +
                   (preview.analyses.find(a => a.type === 'plot')?.item_count || 0)} 项设定
                </Typography>
              </Box>
            }
          />
          {/* 🆕 导入章节选项 */}
          <FormControlLabel
            control={
              <Checkbox
                checked={importChapters}
                onChange={(e) => setImportChapters(e.target.checked)}
                disabled={preview.book.total_chapters === 0}
              />
            }
            label={
              <Box>
                <Typography variant="body2">章节内容</Typography>
                <Typography variant="caption" color="text.secondary">
                  {preview.book.total_chapters} 章正文内容
                </Typography>
              </Box>
            }
          />
        </Box>

        <Divider sx={{ my: 2 }} />

        <Typography variant="caption" color="text.secondary">
          {importChapters 
            ? '导入后将创建新项目，并导入所有章节内容到章节列表，便于续写或改写。'
            : '导入后将创建新项目，并预填充设定和人物信息，便于基于原书内容进行续写或改编。'
          }
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading}>
          取消
        </Button>
        <Button variant="contained" color="success" onClick={handleImport} disabled={loading}>
          {loading ? <CircularProgress size={20} /> : '开始导入'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// 分析结果展示
function AnalysisDisplay({ analyses }: { analyses: BookAnalysis[] }) {
  const typeIcons: Record<string, React.ReactNode> = {
    characters: <PersonIcon />,
    worldview: <PublicIcon />,
    plot: <TimelineIcon />,
    style: <BrushIcon />,
  }

  const typeLabels: Record<string, string> = {
    characters: '人物体系',
    worldview: '世界观设定',
    plot: '情节脉络',
    style: '写作风格',
  }

  if (analyses.length === 0) {
    return (
      <Alert severity="info">
        暂无分析结果，请先执行AI分析
      </Alert>
    )
  }

  return (
    <Box>
      {analyses.map((analysis) => (
        <Accordion key={analysis.id} sx={{ mb: 1 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {typeIcons[analysis.analysis_type]}
              <Typography>{typeLabels[analysis.analysis_type] || analysis.analysis_type}</Typography>
              <Chip size="small" label={`${Math.round(analysis.confidence * 100)}%`} />
            </Box>
          </AccordionSummary>
          <AccordionDetails>
            <AnalysisContent type={analysis.analysis_type} content={analysis.content} />
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  )
}

// 分析内容详情
function AnalysisContent({ type, content }: { type: string; content: Record<string, any> }) {
  if (type === 'characters') {
    return (
      <Box>
        {content.main_characters?.length > 0 && (
          <>
            <Typography variant="subtitle2" gutterBottom>主要人物</Typography>
            <List dense>
              {content.main_characters.map((char: any, i: number) => (
                <ListItem key={i}>
                  <ListItemText
                    primary={char.name}
                    secondary={char.description}
                  />
                </ListItem>
              ))}
            </List>
          </>
        )}
        {content.supporting_characters?.length > 0 && (
          <>
            <Divider sx={{ my: 1 }} />
            <Typography variant="subtitle2" gutterBottom>配角</Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {content.supporting_characters.map((char: any, i: number) => (
                <Chip key={i} size="small" label={char.name} />
              ))}
            </Box>
          </>
        )}
      </Box>
    )
  }

  if (type === 'worldview') {
    return (
      <Box>
        {content.world_type && (
          <Typography variant="body2" gutterBottom>
            <strong>世界类型：</strong>{content.world_type}
          </Typography>
        )}
        {content.world_description && (
          <Typography variant="body2" gutterBottom>
            {content.world_description}
          </Typography>
        )}
        {content.power_systems?.length > 0 && (
          <>
            <Typography variant="subtitle2" sx={{ mt: 1 }}>力量体系</Typography>
            {content.power_systems.map((sys: any, i: number) => (
              <Box key={i} sx={{ ml: 2 }}>
                <Typography variant="body2"><strong>{sys.name}</strong></Typography>
                {sys.levels && (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                    {sys.levels.map((level: string, j: number) => (
                      <Chip key={j} size="small" variant="outlined" label={level} />
                    ))}
                  </Box>
                )}
              </Box>
            ))}
          </>
        )}
      </Box>
    )
  }

  if (type === 'plot') {
    return (
      <Box>
        {content.main_plot && (
          <Typography variant="body2" paragraph>
            {content.main_plot}
          </Typography>
        )}
        {content.plot_arcs?.length > 0 && (
          <>
            <Typography variant="subtitle2">剧情弧</Typography>
            <List dense>
              {content.plot_arcs.map((arc: any, i: number) => (
                <ListItem key={i}>
                  <ListItemText
                    primary={arc.name}
                    secondary={`${arc.chapters?.[0] || '?'}-${arc.chapters?.[1] || '?'}章 · ${arc.description || ''}`}
                  />
                </ListItem>
              ))}
            </List>
          </>
        )}
      </Box>
    )
  }

  if (type === 'style') {
    return (
      <Box>
        {content.narrative_perspective && (
          <Typography variant="body2" gutterBottom>
            <strong>叙事视角：</strong>{content.narrative_perspective}
          </Typography>
        )}
        {content.tone && (
          <Typography variant="body2" gutterBottom>
            <strong>基调：</strong>{content.tone}
          </Typography>
        )}
        {content.pacing && (
          <Typography variant="body2" gutterBottom>
            <strong>节奏：</strong>{content.pacing}
          </Typography>
        )}
        {content.strengths?.length > 0 && (
          <Box sx={{ mt: 1 }}>
            <Typography variant="subtitle2">写作优点</Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
              {content.strengths.map((s: string, i: number) => (
                <Chip key={i} size="small" color="success" variant="outlined" label={s} />
              ))}
            </Box>
          </Box>
        )}
      </Box>
    )
  }

  // 默认：显示 JSON
  return (
    <Box component="pre" sx={{ fontSize: 12, overflow: 'auto', maxHeight: 400 }}>
      {JSON.stringify(content, null, 2)}
    </Box>
  )
}

// ==================== 主页面 ====================

export default function BookParserPage() {
  const navigate = useNavigate()
  const location = useLocation()

  // 状态
  const [books, setBooks] = useState<BookSource[]>([])
  const [selectedBook, setSelectedBook] = useState<BookSource | null>(null)
  const [chapters, setChapters] = useState<BookChapter[]>([])
  const [analyses, setAnalyses] = useState<BookAnalysis[]>([])
  const [loading, setLoading] = useState(false)
  const [taskStatus, setTaskStatus] = useState<ParseStatus | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [detailTab, setDetailTab] = useState(0)
  const [importOpen, setImportOpen] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null)
  const [prefillTitle, setPrefillTitle] = useState('')
  const [prefillContent, setPrefillContent] = useState('')
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [bookToDelete, setBookToDelete] = useState<BookSource | null>(null)
  const [deleting, setDeleting] = useState(false)

  // 加载书籍列表
  const loadBooks = useCallback(async () => {
    try {
      const list = await bookParserApi.getBookList()
      setBooks(list)
    } catch (err) {
      console.error('加载书籍列表失败:', err)
    }
  }, [])

  // 如果从耳畔星河跳转过来，自动打开上传对话框并填充文本
  useEffect(() => {
    const state = (location as any).state as
      | { openUpload?: boolean; prefillTitle?: string; prefillContent?: string; from?: string }
      | undefined

    if (state?.openUpload) {
      if (state.prefillTitle) {
        setPrefillTitle(state.prefillTitle)
      }
      if (state.prefillContent) {
        setPrefillContent(state.prefillContent)
      }
      setUploadOpen(true)

      // 清理路由状态，避免刷新或返回时重复弹出
      navigate(location.pathname, { replace: true, state: null })
    }
  }, [location, navigate])

  // 保存来源信息
  const [sourcePage, setSourcePage] = useState<string>('/home')

  useEffect(() => {
    const state = (location as any).state as
      | { from?: string }
      | undefined
    if (state?.from) {
      setSourcePage(state.from)
    }
  }, [location])

  useEffect(() => {
    loadBooks()
  }, [loadBooks])

  // 选择书籍
  const handleSelectBook = async (book: BookSource) => {
    setSelectedBook(book)
    setDetailTab(0)
    setTaskStatus(null)

    // 加载章节和分析结果
    try {
      const [chaptersData, analysesData] = await Promise.all([
        bookParserApi.getBookChapters(book.id),
        bookParserApi.getBookAnalyses(book.id),
      ])
      setChapters(chaptersData)
      setAnalyses(analysesData)
    } catch (err) {
      console.error('加载书籍详情失败:', err)
    }
  }

  // 删除书籍（弹出确认对话框）
  const handleDeleteBook = (book: BookSource) => {
    setBookToDelete(book)
    setDeleteConfirmOpen(true)
  }

  const handleConfirmDeleteBook = async () => {
    if (!bookToDelete) return

    try {
      setDeleting(true)
      await bookParserApi.deleteBook(bookToDelete.id)
      setBooks((prev) => prev.filter((b) => b.id !== bookToDelete.id))
      if (selectedBook?.id === bookToDelete.id) {
        setSelectedBook(null)
      }
    } catch (err) {
      console.error('删除失败:', err)
    } finally {
      setDeleting(false)
      setDeleteConfirmOpen(false)
      setBookToDelete(null)
    }
  }

  // 执行解析
  const handleParse = async () => {
    if (!selectedBook) return

    try {
      setLoading(true)
      await bookParserApi.parseBook(selectedBook.id)

      // 轮询状态
      bookParserApi.pollStatus(
        selectedBook.id,
        (status) => setTaskStatus(status),
        async (status) => {
          setTaskStatus(status)
          setLoading(false)
          // 刷新章节列表
          const chaptersData = await bookParserApi.getBookChapters(selectedBook.id)
          setChapters(chaptersData)
          // 刷新书籍信息
          const bookData = await bookParserApi.getBook(selectedBook.id)
          setSelectedBook(bookData)
        },
        (err) => {
          setTaskStatus({ status: 'failed', progress: 0, message: '解析失败', chapters_count: null, error: err.message })
          setLoading(false)
        }
      )
    } catch (err: any) {
      setLoading(false)
      alert(err.response?.data?.detail || '启动解析失败')
    }
  }

  // 执行分析
  const handleAnalyze = async () => {
    if (!selectedBook) return

    try {
      setLoading(true)
      await bookParserApi.analyzeBook(selectedBook.id)

      // 轮询状态
      bookParserApi.pollStatus(
        selectedBook.id,
        (status) => setTaskStatus(status),
        async (status) => {
          setTaskStatus(status)
          setLoading(false)
          // 刷新分析结果
          const analysesData = await bookParserApi.getBookAnalyses(selectedBook.id)
          setAnalyses(analysesData)
          // 刷新书籍信息
          const bookData = await bookParserApi.getBook(selectedBook.id)
          setSelectedBook(bookData)
        },
        (err) => {
          setTaskStatus({ status: 'failed', progress: 0, message: '分析失败', chapters_count: null, error: err.message })
          setLoading(false)
        }
      )
    } catch (err: any) {
      setLoading(false)
      alert(err.response?.data?.detail || '启动分析失败')
    }
  }

  // 上传成功
  const handleUploadSuccess = (book: BookSource) => {
    setBooks([book, ...books])
    setSelectedBook(book)
    setChapters([])
    setAnalyses([])
  }

  // 返回列表
  const handleBack = () => {
    setSelectedBook(null)
    setChapters([])
    setAnalyses([])
    setTaskStatus(null)
  }

  // 打开导入对话框
  const handleOpenImport = async () => {
    if (!selectedBook) return
    
    try {
      const preview = await bookParserApi.getImportPreview(selectedBook.id)
      setImportPreview(preview)
      setImportOpen(true)
    } catch (err: any) {
      alert(err.response?.data?.detail || '获取导入预览失败')
    }
  }

  // 执行导入
  const handleImport = async (options: ImportRequest) => {
    if (!selectedBook) return
    
    try {
      setImporting(true)
      const result = await bookParserApi.importToProject(selectedBook.id, options)
      setImportOpen(false)
      setImporting(false)
      
      // 刷新书籍信息
      const bookData = await bookParserApi.getBook(selectedBook.id)
      setSelectedBook(bookData)
      
      // 检查是否从耳畔星河跳转过来
      const fromAudiobook = (location as any).state?.from === 'audiobook'
      
      // 提示成功并跳转
      if (fromAudiobook) {
        // 如果是从耳畔星河来的，提供返回选项
        const choice = confirm(
          `导入成功！已创建项目《${result.project_title}》\n\n` +
          `点击"确定"跳转到工作流\n` +
          `点击"取消"返回耳畔星河`
        )
        if (choice) {
          navigate(`/workflow/${result.project_id}`)
        } else {
          navigate('/audiobook')
        }
      } else {
        // 原有逻辑：直接跳转到工作流
        if (confirm(`导入成功！已创建项目《${result.project_title}》\n\n是否立即跳转到该项目？`)) {
          navigate(`/workflow/${result.project_id}`)
        }
      }
    } catch (err: any) {
      setImporting(false)
      alert(err.response?.data?.detail || '导入失败')
    }
  }

  // 🆕 重置导入状态（允许重新导入）
  const handleResetImport = async () => {
    if (!selectedBook) return
    
    if (!confirm('确定要重置导入状态吗？\n\n重置后可以重新导入为新项目，但之前导入的项目不会被删除。')) {
      return
    }
    
    try {
      setLoading(true)
      await bookParserApi.resetImportStatus(selectedBook.id)
      
      // 刷新书籍信息
      const bookData = await bookParserApi.getBook(selectedBook.id)
      setSelectedBook(bookData)
      setLoading(false)
      
      alert('已重置导入状态，可以重新导入为新项目')
    } catch (err: any) {
      setLoading(false)
      alert(err.response?.data?.detail || '重置失败')
    }
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: '#f5f5f5' }}>
      {/* 顶部导航 */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <IconButton onClick={() => navigate(sourcePage)}>
            <ArrowBackIcon />
          </IconButton>
          <ArticleIcon color="primary" />
          <Typography variant="h5">拆书工具</Typography>
        </Box>
      </Paper>

      <Container maxWidth="lg">
        {!selectedBook ? (
          // 书籍列表视图
          <>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
              <Typography variant="h6">我的书籍</Typography>
              <Button
                variant="contained"
                startIcon={<CloudUploadIcon />}
                onClick={() => setUploadOpen(true)}
              >
                上传书籍
              </Button>
            </Box>

            {books.length === 0 ? (
              <Paper sx={{ p: 4, textAlign: 'center' }}>
                <ArticleIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
                <Typography color="text.secondary">
                  还没有上传任何书籍
                </Typography>
                <Button
                  variant="outlined"
                  sx={{ mt: 2 }}
                  onClick={() => setUploadOpen(true)}
                >
                  上传第一本书
                </Button>
              </Paper>
            ) : (
              <Grid container spacing={2}>
                {books.map((book) => (
                  <Grid item xs={12} sm={6} md={4} key={book.id}>
                    <BookCard
                      book={book}
                      onSelect={() => handleSelectBook(book)}
                      onDelete={() => handleDeleteBook(book)}
                    />
                  </Grid>
                ))}
              </Grid>
            )}
          </>
        ) : (
          // 书籍详情视图
          <>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
              <Button startIcon={<ArrowBackIcon />} onClick={handleBack}>
                返回列表
              </Button>
              <Typography variant="h6" sx={{ flexGrow: 1 }}>
                {selectedBook.title}
              </Typography>
              {selectedBook.author && (
                <Typography color="text.secondary">作者：{selectedBook.author}</Typography>
              )}
            </Box>

            {/* 任务进度 */}
            {taskStatus && (loading || taskStatus.status === 'failed') && (
              <Alert
                severity={taskStatus.status === 'failed' ? 'error' : 'info'}
                sx={{ mb: 2 }}
              >
                <Typography variant="body2">{taskStatus.message}</Typography>
                {taskStatus.progress > 0 && taskStatus.progress < 100 && (
                  <LinearProgress variant="determinate" value={taskStatus.progress} sx={{ mt: 1 }} />
                )}
                {taskStatus.error && (
                  <Typography variant="caption" color="error">
                    {taskStatus.error}
                  </Typography>
                )}
              </Alert>
            )}

            {/* 操作按钮 */}
            <Paper sx={{ p: 2, mb: 2 }}>
              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                <Chip label={`${selectedBook.total_words.toLocaleString()} 字`} />
                <Chip label={`${selectedBook.total_chapters} 章`} />

                <Box sx={{ flexGrow: 1 }} />

                <Button
                  variant="outlined"
                  startIcon={<PlayArrowIcon />}
                  onClick={handleParse}
                  disabled={loading || selectedBook.status === 'parsing'}
                >
                  {selectedBook.total_chapters > 0 ? '重新解析章节' : '解析章节'}
                </Button>

                <Button
                  variant="contained"
                  startIcon={<AnalyticsIcon />}
                  onClick={handleAnalyze}
                  disabled={loading || chapters.length === 0 || selectedBook.status === 'analyzing'}
                >
                  AI 分析
                </Button>

                <Tooltip title={selectedBook.imported_project_id ? '点击重置导入状态，允许重新导入' : '将分析结果导入为工作流项目'}>
                  <span>
                    {selectedBook.imported_project_id ? (
                      <Button
                        variant="outlined"
                        color="warning"
                        startIcon={<ImportExportIcon />}
                        disabled={loading}
                        onClick={handleResetImport}
                      >
                        已导入 (点击重置)
                      </Button>
                    ) : (
                      <Button
                        variant="outlined"
                        color="success"
                        startIcon={<ImportExportIcon />}
                        disabled={loading || selectedBook.status !== 'completed'}
                        onClick={handleOpenImport}
                      >
                        导入项目
                      </Button>
                    )}
                  </span>
                </Tooltip>
              </Box>
            </Paper>

            {/* 详情标签页 */}
            <Paper>
              <Tabs value={detailTab} onChange={(_, v) => setDetailTab(v)}>
                <Tab label={`章节列表 (${chapters.length})`} />
                <Tab label={`分析结果 (${analyses.length})`} />
              </Tabs>
              <Box sx={{ p: 2 }}>
                {detailTab === 0 && (
                  chapters.length === 0 ? (
                    <Alert severity="info">
                      暂无章节，请先执行章节解析
                    </Alert>
                  ) : (
                    <List dense sx={{ maxHeight: 500, overflow: 'auto' }}>
                      {chapters.map((ch) => (
                        <ListItem key={ch.id} divider>
                          <ListItemText
                            primary={`第${ch.chapter_number}章 ${ch.title}`}
                            secondary={`${ch.word_count.toLocaleString()} 字${ch.volume_title ? ` · ${ch.volume_title}` : ''}`}
                          />
                          <Chip
                            size="small"
                            variant="outlined"
                            label={ch.chapter_type === 'normal' ? '正文' : ch.chapter_type}
                          />
                        </ListItem>
                      ))}
                    </List>
                  )
                )}
                {detailTab === 1 && <AnalysisDisplay analyses={analyses} />}
              </Box>
            </Paper>
          </>
        )}
      </Container>

      {/* 上传对话框 */}
      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUpload={handleUploadSuccess}
        initialTitle={prefillTitle}
        initialContent={prefillContent}
      />

      {/* 导入对话框 */}
      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        preview={importPreview}
        loading={importing}
        onImport={handleImport}
      />

      {/* 删除书籍确认对话框 */}
      <Dialog
        open={deleteConfirmOpen}
        onClose={() => {
          if (!deleting) {
            setDeleteConfirmOpen(false)
            setBookToDelete(null)
          }
        }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>删除书籍</DialogTitle>
        <DialogContent>
          <Typography variant="body1" sx={{ mb: 1 }}>
            确定要删除《{bookToDelete?.title}》吗？
          </Typography>
          <Typography variant="caption" color="text.secondary">
            该操作只会删除拆书工具中的书籍及解析结果，不会影响已经导入的创作项目。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setDeleteConfirmOpen(false)
              setBookToDelete(null)
            }}
            disabled={deleting}
          >
            取消
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleConfirmDeleteBook}
            disabled={deleting}
          >
            {deleting ? <CircularProgress size={20} color="inherit" /> : '删除'}
          </Button>
        </DialogActions>
      </Dialog>

    </Box>
  )
}
