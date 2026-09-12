import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
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
      setStatusText(nextStatus.message || t('bookParserUpload.processing'))

      if (nextStatus.status === 'failed') {
        throw new Error(nextStatus.error || nextStatus.message || t('bookParserUpload.taskFailed'))
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
    setStatusText(t('bookParserUpload.uploading'))

    try {
      let book: BookSource

      if (tabIndex === 0) {
        if (!title.trim() || !content.trim()) {
          setError(t('bookParserUpload.fillTitleAndContent'))
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
          setError(t('bookParserUpload.selectFile'))
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
      setStatusText(t('bookParserUpload.uploadOkChapters'))
      await bookParserApi.parseBook(book.id)
      const parseStatus = await waitForBookStatus(book.id, ['chapters_done', 'completed'])

      if (parseStatus.status !== 'completed') {
        setProgress(56)
        setStatusText(t('bookParserUpload.chaptersOkAnalyzing'))
        await bookParserApi.analyzeBook(book.id)
        await waitForBookStatus(book.id, ['completed'])
      }

      setProgress(88)
      setStatusText(t('bookParserUpload.analyzingImporting'))

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
      setStatusText(t('bookParserUpload.analyzingImported'))
      onUploadSuccess?.(importedBook)
      resetForm()
      onClose()
    } catch (err: any) {
      const errMsg = await extractApiErrorMessage(err, t('bookParserUpload.uploadParseImportFailed'))
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
      <DialogTitle>{t('bookParserUpload.title')}</DialogTitle>
      <DialogContent>
        <Tabs value={tabIndex} onChange={(_, value) => setTabIndex(value)} sx={{ mb: 2 }}>
          <Tab label={t('bookParserUpload.tabPaste')} />
          <Tab label={t('bookParserUpload.tabUpload')} />
        </Tabs>

        <Alert severity="info" sx={{ mb: 2 }}>
          {t('bookParserUpload.autoFlowHint')}
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
                {statusText || t('bookParserUpload.processing')}
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
          label={t('bookParserUpload.bookTitle')}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          sx={{ mb: 2 }}
          disabled={loading}
        />
        <TextField
          fullWidth
          label={t('bookParserUpload.authorOptional')}
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
            label={t('bookParserUpload.bookContent')}
            placeholder={t('bookParserUpload.contentPlaceholder')}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            disabled={loading}
          />
        ) : (
          <Box
            sx={{
              border: '2px dashed',
              borderColor: file ? 'success.main' : 'divider',
              borderRadius: 2,
              p: 4,
              textAlign: 'center',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
              '&:hover': { borderColor: file ? 'success.main' : 'primary.main' },
            }}
            onClick={() => {
              if (loading) return
              document.getElementById('file-input')?.click()
            }}
          >
            <input
              id="file-input"
              type="file"
              accept=".txt,.md,.markdown,.epub,.pdf"
              hidden
              disabled={loading}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <CloudUploadIcon sx={{ fontSize: 48, color: file ? 'success.main' : 'text.secondary', mb: 1 }} />
            <Typography
              variant="body1"
              color={file ? 'success.main' : 'text.secondary'}
              sx={file ? { fontWeight: 600 } : undefined}
            >
              {file ? file.name : t('bookParserUpload.clickSelectFile')}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('bookParserUpload.supportedFormats')}
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          {t('action.cancel')}
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={loading}>
          {loading ? <CircularProgress size={20} /> : t('bookParserUpload.uploadAndAnalyze')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
