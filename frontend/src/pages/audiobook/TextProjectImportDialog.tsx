import {
  Alert,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material'

import { useTranslation } from 'react-i18next'

import { useFormats } from '@/i18n'
import { audiobookButtonSx } from './audiobookTheme'

interface TextProjectImportDialogProps {
  open: boolean
  title: string
  text: string
  creating: boolean
  onClose: () => void
  onTitleChange: (value: string) => void
  onTextChange: (value: string) => void
  onCreate: () => void
}

const TextProjectImportDialog = ({
  open,
  title,
  text,
  creating,
  onClose,
  onTitleChange,
  onTextChange,
  onCreate,
}: TextProjectImportDialogProps) => {
  // 原本是无函数体的箭头组件，为了拿到绑定语言的格式化函数才补上函数体。
  const { t } = useTranslation()
  const { formatNumber } = useFormats()

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!creating) {
          onClose()
        }
      }}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>{t('audiobook.textProjectImportDialog.title')}</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>
          {t('audiobook.textProjectImportDialog.alertHint')}
        </Alert>
        <TextField
          fullWidth
          label={t('audiobook.textProjectImportDialog.projectNameLabel')}
          value={title}
          onChange={(event) => onTitleChange(event.target.value)}
          placeholder={t('audiobook.textProjectImportDialog.projectNamePlaceholder')}
          sx={{ mb: 2 }}
        />
        <TextField
          fullWidth
          multiline
          rows={12}
          label={t('audiobook.textProjectImportDialog.bookContentLabel')}
          placeholder={t('audiobook.textProjectImportDialog.bookContentPlaceholder')}
          value={text}
          onChange={(event) => onTextChange(event.target.value)}
        />
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          {t('audiobook.textProjectImportDialog.currentLength', { count: formatNumber(text.trim().length) })}
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={creating}>
          {t('action.cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={onCreate}
          disabled={creating}
          startIcon={creating ? <CircularProgress size={18} color="inherit" /> : undefined}
          sx={audiobookButtonSx.brandContained}
        >
          {creating ? t('audiobook.textProjectImportDialog.creating') : t('audiobook.textProjectImportDialog.submit')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default TextProjectImportDialog
