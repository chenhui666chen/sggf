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
}: TextProjectImportDialogProps) => (
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
    <DialogTitle>从文本创建新项目</DialogTitle>
    <DialogContent>
      <Alert severity="info" sx={{ mb: 2 }}>
        粘贴整本书或长篇文本，系统会自动拆分章节并创建项目，随后可以在本页生成有声书。
      </Alert>
      <TextField
        fullWidth
        label="项目名称"
        value={title}
        onChange={(event) => onTitleChange(event.target.value)}
        placeholder="例如：某某小说 有声化项目"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        multiline
        rows={12}
        label="书籍全文或长篇文本"
        placeholder="将整本书的文本粘贴到这里..."
        value={text}
        onChange={(event) => onTextChange(event.target.value)}
      />
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
        当前长度：{text.trim().length.toLocaleString()} 字；系统会自动拆分章节并创建项目。
      </Typography>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={creating}>
        取消
      </Button>
      <Button
        variant="contained"
        onClick={onCreate}
        disabled={creating}
        startIcon={creating ? <CircularProgress size={18} color="inherit" /> : undefined}
        sx={audiobookButtonSx.brandContained}
      >
        {creating ? '创建中...' : '创建并开始配置音色'}
      </Button>
    </DialogActions>
  </Dialog>
)

export default TextProjectImportDialog
