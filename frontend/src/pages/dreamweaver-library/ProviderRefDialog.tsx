import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material'

export interface ProviderRefDialogProps {
  open: boolean
  assetRole: string
  subjectId: string
  submitting: boolean
  error: string | null
  onSubjectIdChange: (v: string) => void
  onClose: () => void
  onSubmit: () => void
}

export function ProviderRefDialog(props: ProviderRefDialogProps) {
  const { open, assetRole, subjectId, submitting, error, onSubjectIdChange, onClose, onSubmit } = props

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>绑定 Kling 主体</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          将 Kling 角色主体（subject_id）绑定到此素材，用于 I2V 视频生成时保持角色一致性。
          留空 subject_id 可解绑。
        </Typography>
        <TextField
          fullWidth
          size="small"
          label="Kling Subject ID"
          value={subjectId}
          onChange={(e) => onSubjectIdChange(e.target.value)}
          placeholder="输入 Kling subject_id..."
          disabled={submitting}
          sx={{ mb: 1 }}
        />
        <Typography variant="caption" color="text.secondary">
          角色：{assetRole}
        </Typography>
        {error && (
          <Alert severity="error" sx={{ mt: 1, borderRadius: 2 }}>
            {error}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>
          取消
        </Button>
        <Button
          variant="contained"
          onClick={() => void onSubmit()}
          disabled={submitting}
        >
          {submitting ? '绑定中...' : subjectId.trim() ? '绑定' : '解绑'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
