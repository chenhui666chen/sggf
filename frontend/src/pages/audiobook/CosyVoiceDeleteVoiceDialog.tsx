import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'

export interface PendingDeleteVoice {
  id: string
  label: string
}

interface CosyVoiceDeleteVoiceDialogProps {
  pendingDeleteVoice: PendingDeleteVoice | null
  cloneDeletingId: string | null
  onClose: () => void
  onConfirm: () => void
}

const CosyVoiceDeleteVoiceDialog = ({
  pendingDeleteVoice,
  cloneDeletingId,
  onClose,
  onConfirm,
}: CosyVoiceDeleteVoiceDialogProps) => (
  <Dialog
    open={Boolean(pendingDeleteVoice)}
    onClose={onClose}
    fullWidth
    maxWidth="xs"
  >
    <DialogTitle>删除自定义音色</DialogTitle>
    <DialogContent dividers>
      <Typography variant="body2">
        确定要删除自定义音色「{pendingDeleteVoice?.label || ''}」吗？该操作会从当前账号移除该音色，无法恢复。
      </Typography>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={Boolean(cloneDeletingId)}>
        取消
      </Button>
      <Button
        color="error"
        variant="contained"
        onClick={onConfirm}
        disabled={Boolean(cloneDeletingId)}
      >
        删除
      </Button>
    </DialogActions>
  </Dialog>
)

export default CosyVoiceDeleteVoiceDialog
