import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
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
  deleteFiles: boolean
  deleting: boolean
  onClose: () => void
  onReasonChange: (value: string) => void
  onDeleteFilesChange: (value: boolean) => void
  onDelete: () => void
}

const ChapterDeleteConfirmDialog = ({
  open,
  chapter,
  reason,
  deleteFiles,
  deleting,
  onClose,
  onReasonChange,
  onDeleteFilesChange,
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
        此操作将删除章节及其相关数据，请谨慎操作！
      </Alert>

      <Typography variant="body1" sx={{ mb: 2 }}>
        确定要删除以下章节吗？
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
        删除后将影响以下内容：
      </Typography>

      <List dense>
        <ListItem>
          <ListItemText primary="章节内容" secondary="章节的文本内容将被删除" />
        </ListItem>
        <ListItem>
          <ListItemText primary="有声剧本" secondary="已生成的有声剧本将被删除" />
        </ListItem>
        <ListItem>
          <ListItemText primary="音频文件" secondary="已生成的音频文件将被删除（可选）" />
        </ListItem>
        <ListItem>
          <ListItemText primary="章节关联" secondary="章节与角色、设定的关联将被移除" />
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

      <FormControlLabel
        control={
          <Checkbox
            checked={deleteFiles}
            onChange={(event) => onDeleteFilesChange(event.target.checked)}
            sx={{
              color: audiobookColorRoles.destructiveAction.main,
              '&.Mui-checked': {
                color: audiobookColorRoles.destructiveAction.main,
              },
            }}
          />
        }
        label="同时删除音频文件（不可恢复）"
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
