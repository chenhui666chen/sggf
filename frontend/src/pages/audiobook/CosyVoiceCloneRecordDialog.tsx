import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'

interface CosyVoiceCloneRecordDialogProps {
  open: boolean
  cloneRecording: boolean
  cloneLoading: boolean
  cloneUploading: boolean
  onClose: () => void
  onStartCloneRecording: () => void
  onStopCloneRecording: () => void
}

const CosyVoiceCloneRecordDialog = ({
  open,
  cloneRecording,
  cloneLoading,
  cloneUploading,
  onClose,
  onStartCloneRecording,
  onStopCloneRecording,
}: CosyVoiceCloneRecordDialogProps) => (
  <Dialog
    open={open}
    onClose={onClose}
    fullWidth
    maxWidth="sm"
    disableEscapeKeyDown={cloneRecording}
  >
    <DialogTitle>录音朗读提示</DialogTitle>
    <DialogContent dividers>
      <Typography variant="body2" sx={{ mb: 1 }}>
        朗读示例（约10秒）：“时间会缓和所有的悲伤，当你的悲伤被安抚以后，你就会因为认识过我而感到满足。”
      </Typography>
      <Typography variant="caption" color="text.secondary">
        也可以随机读其他内容。
      </Typography>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={cloneRecording}>
        关闭
      </Button>
      <Button
        variant="contained"
        color={cloneRecording ? 'error' : 'primary'}
        onClick={cloneRecording ? onStopCloneRecording : onStartCloneRecording}
        disabled={cloneLoading || cloneUploading}
      >
        {cloneRecording ? '结束录音并上传' : '开始录音'}
      </Button>
    </DialogActions>
  </Dialog>
)

export default CosyVoiceCloneRecordDialog
