import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemText,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import WarningIcon from '@mui/icons-material/Warning'
import { useTranslation } from 'react-i18next'

import { audiobookButtonSx, audiobookColorRoles } from './audiobookTheme'
import type { Chapter } from './types'

interface ChapterDeleteConfirmDialogProps {
  open: boolean
  chapter: Chapter | null
  reason: string
  deleting: boolean
  onClose: () => void
  onReasonChange: (value: string) => void
  onDelete: () => void
}

const ChapterDeleteConfirmDialog = ({
  open,
  chapter,
  reason,
  deleting,
  onClose,
  onReasonChange,
  onDelete,
}: ChapterDeleteConfirmDialogProps) => {
  const { t } = useTranslation()
  return (
  <Dialog
    open={open}
    onClose={onClose}
    maxWidth="sm"
    fullWidth
  >
    <DialogTitle>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <WarningIcon sx={{ color: audiobookColorRoles.destructiveAction.main }} />
        <Typography variant="h6">{t('audiobook.chapterDeleteConfirmDialog.title')}</Typography>
      </Box>
    </DialogTitle>
    <DialogContent>
      <Alert severity="warning" sx={{ mb: 2 }}>
        {t('audiobook.chapterDeleteConfirmDialog.alertText')}
      </Alert>

      <Typography variant="body1" sx={{ mb: 2 }}>
        {t('audiobook.chapterDeleteConfirmDialog.confirmQuestion')}
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2, backgroundColor: audiobookColorRoles.destructiveAction.softBg }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {chapter && t('audiobook.chapterDeleteConfirmDialog.chapterLabel', {
            number: chapter.chapter_number,
            title: chapter.title,
          })}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {chapter?.content ? `${chapter.content.slice(0, 100)}...` : t('audiobook.chapterDeleteConfirmDialog.noContent')}
        </Typography>
      </Paper>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('audiobook.chapterDeleteConfirmDialog.cleanupIntro')}
      </Typography>

      <List dense>
        <ListItem>
          <ListItemText
            primary={t('audiobook.chapterDeleteConfirmDialog.scriptItem')}
            secondary={t('audiobook.chapterDeleteConfirmDialog.scriptItemHint')}
          />
        </ListItem>
        <ListItem>
          <ListItemText
            primary={t('audiobook.chapterDeleteConfirmDialog.audioItem')}
            secondary={t('audiobook.chapterDeleteConfirmDialog.audioItemHint')}
          />
        </ListItem>
        <ListItem>
          <ListItemText
            primary={t('audiobook.chapterDeleteConfirmDialog.taskItem')}
            secondary={t('audiobook.chapterDeleteConfirmDialog.taskItemHint')}
          />
        </ListItem>
      </List>

      <TextField
        fullWidth
        multiline
        rows={3}
        label={t('audiobook.chapterDeleteConfirmDialog.reasonLabel')}
        placeholder={t('audiobook.chapterDeleteConfirmDialog.reasonPlaceholder')}
        value={reason}
        onChange={(event) => onReasonChange(event.target.value)}
        sx={{ mb: 2 }}
      />

    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={deleting}>
        {t('action.cancel')}
      </Button>
      <Button
        onClick={onDelete}
        disabled={deleting}
        variant="contained"
        startIcon={deleting ? <CircularProgress size={18} color="inherit" /> : undefined}
        sx={audiobookButtonSx.dangerContained}
      >
        {deleting
          ? t('audiobook.chapterDeleteConfirmDialog.deleting')
          : t('audiobook.chapterDeleteConfirmDialog.confirmDelete')}
      </Button>
    </DialogActions>
  </Dialog>
  )
}

export default ChapterDeleteConfirmDialog
