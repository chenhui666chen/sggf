import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import * as bookParserApi from '@/services/bookParserApi'
import type { BookSource } from '@/services/bookParserApi'
import { extractApiErrorMessage } from '@/services/api'

interface BookParserUploadDialogProps {
  open: boolean
  onClose: () => void
  onUploadSuccess?: (book: BookSource) => void
  initialTitle?: string
  initialContent?: string
}

export default function BookParserUploadDialog({
  open,
  onClose,
  onUploadSuccess,
  initialTitle = '',
  initialContent = '',
}: BookParserUploadDialogProps) {
  const [tabIndex, setTabIndex] = useState(0)
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [content, setContent] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState(0)
  const [statusText, setStatusText] = useState('')

  useEffect(() => {
    if (!open) return

    if (initialTitle) {
      setTitle(initialTitle)
    }
    if (initialContent) {
      setContent(initialContent)
    }
  }, [open, initialTitle, initialContent])

  const resetForm = () => {
    setTitle('')
    setAuthor('')
    setContent('')
    setFile(null)
    setError('')
    setProgress(0)
    setStatusText('')
    setTabIndex(0)
  }

  const handleClose = () => {
    if (loading) return
    resetForm()
    onClose()
  }

  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

  const mapProgress = (status: bookParserApi.ParseStatus): number => {
    const raw = Math.max(0, Math.min(100, Number(status.progress || 0)))

    if (status.status === 'parsing' || status.status === 'chapters_done') {
      return Math.round(10 + raw * 0.4)
    }
    if (status.status === 'analyzing' || status.status === 'completed') {
      return Math.round(52 + raw * 0.33)
    }
    if (status.status === 'failed') {
      return Math.max(progress, 10)
    }
    return raw
  }

  const waitForBookStatus = async (
    bookId: number,
    terminalStatuses: string[]
  ): Promise<bookParserApi.ParseStatus> => {
    while (true) {
      const nextStatus = await bookParserApi.getParseStatus(bookId)
      setProgress(mapProgress(nextStatus))
      setStatusText(nextStatus.message || '正在处理...')

      if (nextStatus.status === 'failed') {
        throw new Error(nextStatus.error || nextStatus.message || '拆书任务失败')
      }

      if (terminalStatuses.includes(nextStatus.status)) {
        return nextStatus
      }

      await sleep(1500)
    }
  }

  const handleSubmit = async () => {
    setLoading(true)
    setError('')
    setProgress(2)
    setStatusText('正在上传书籍...')

    try {
      let book: BookSource

      if (tabIndex === 0) {
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
        if (!file) {
          setError('请选择文件')
          setLoading(false)
          return
        }

        book = await bookParserApi.uploadFile(
          file,
          title.trim() || undefined,
          author.trim() || undefined
        )
      }

      setProgress(8)
      setStatusText('上传成功，开始切分章节...')
      await bookParserApi.parseBook(book.id)
      const parseStatus = await waitForBookStatus(book.id, ['chapters_done', 'completed'])

      if (parseStatus.status !== 'completed') {
        setProgress(56)
        setStatusText('章节切分完成，开始 AI 分析...')
        await bookParserApi.analyzeBook(book.id)
        await waitForBookStatus(book.id, ['completed'])
      }

      setProgress(88)
      setStatusText('拆书分析完成，正在导入灵感方舟...')

      const importResult = await bookParserApi.importToProject(book.id, {
        project_title: title.trim() || book.title,
        import_settings: true,
        import_characters: true,
        import_chapters: true,
      })

      const importedBook: BookSource = {
        ...book,
        imported_project_id: importResult.project_id,
      }

      setProgress(100)
      setStatusText('拆书分析完成，已自动导入灵感方舟')
      onUploadSuccess?.(importedBook)
      resetForm()
      onClose()
    } catch (err: any) {
      const errMsg = await extractApiErrorMessage(err, '上传、拆书或导入失败')
      setError(errMsg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={(_, reason) => {
        if (loading && (reason === 'backdropClick' || reason === 'escapeKeyDown')) return
        handleClose()
      }}
      maxWidth="md"
      fullWidth
      disableEscapeKeyDown={loading}
    >
      <DialogTitle>上传书籍</DialogTitle>
      <DialogContent>
        <Tabs value={tabIndex} onChange={(_, value) => setTabIndex(value)} sx={{ mb: 2 }}>
          <Tab label="粘贴文本" />
          <Tab label="上传文件" />
        </Tabs>

        <Alert severity="info" sx={{ mb: 2 }}>
          上传成功后会自动执行章节切分、AI 分析，并自动导入灵感方舟。
        </Alert>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {loading && (
          <Box sx={{ mb: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.75 }}>
              <Typography variant="body2" color="text.secondary">
                {statusText || '正在处理...'}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {progress}%
              </Typography>
            </Box>
            <LinearProgress variant="determinate" value={progress} />
          </Box>
        )}

        <TextField
          fullWidth
          label="书名"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          sx={{ mb: 2 }}
          disabled={loading}
        />
        <TextField
          fullWidth
          label="作者（可选）"
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          sx={{ mb: 2 }}
          disabled={loading}
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
            disabled={loading}
          />
        ) : (
          <Box
            sx={{
              border: '2px dashed',
              borderColor: 'divider',
              borderRadius: 2,
              p: 4,
              textAlign: 'center',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
              '&:hover': { borderColor: 'primary.main' },
            }}
            onClick={() => {
              if (loading) return
              document.getElementById('file-input')?.click()
            }}
          >
            <input
              id="file-input"
              type="file"
              accept=".txt,.epub,.pdf"
              hidden
              disabled={loading}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <CloudUploadIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
            <Typography variant="body1" color="text.secondary">
              {file ? file.name : '点击选择 TXT / EPUB / PDF 文件'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              支持 TXT、EPUB、PDF，TXT 支持 UTF-8、GBK 编码
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          取消
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={loading}>
          {loading ? <CircularProgress size={20} /> : '上传并开始分析'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
