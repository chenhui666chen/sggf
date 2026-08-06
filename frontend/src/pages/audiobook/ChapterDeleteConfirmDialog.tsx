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
}: ChapterDeleteConfirmDialogProps) => (
  <Dialog
    open={open}
    onClose={onClose}
    maxWidth="sm"
    fullWidth
  >
    <DialogTitle>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <WarningIcon sx={{ color: audiobookColorRoles.destructiveAction.main }} />
        <Typography variant="h6">确认删除章节</Typography>
      </Box>
    </DialogTitle>
    <DialogContent>
      <Alert severity="warning" sx={{ mb: 2 }}>
        此操作将删除该章节的全部有声书产物，原始章节内容不受影响。
      </Alert>

      <Typography variant="body1" sx={{ mb: 2 }}>
        确定要删除以下章节的全部有声书产物吗？
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2, backgroundColor: audiobookColorRoles.destructiveAction.softBg }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {chapter && `第${chapter.chapter_number}章 - ${chapter.title}`}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {chapter?.content ? `${chapter.content.slice(0, 100)}...` : '暂无内容'}
        </Typography>
      </Paper>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        删除后以下全部产物都会被清理：
      </Typography>

      <List dense>
        <ListItem>
          <ListItemText primary="有声剧本" secondary="已生成的有声剧本将被删除" />
        </ListItem>
        <ListItem>
          <ListItemText
            primary="整章与片段音频"
            secondary="整章音频、工作台试听片段及管线片段都会被删除"
          />
        </ListItem>
        <ListItem>
          <ListItemText primary="生成任务" secondary="关联的生成任务记录将被清除" />
        </ListItem>
      </List>

      <TextField
        fullWidth
        multiline
        rows={3}
        label="删除原因（可选）"
        placeholder="请说明删除此章节的原因..."
        value={reason}
        onChange={(event) => onReasonChange(event.target.value)}
        sx={{ mb: 2 }}
      />

    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={deleting}>
        取消
      </Button>
      <Button
        onClick={onDelete}
        disabled={deleting}
        variant="contained"
        startIcon={deleting ? <CircularProgress size={18} color="inherit" /> : undefined}
        sx={audiobookButtonSx.dangerContained}
      >
        {deleting ? '删除中...' : '确认删除'}
      </Button>
    </DialogActions>
  </Dialog>
)

export default ChapterDeleteConfirmDialog
