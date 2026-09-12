import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'

import { useTranslation } from 'react-i18next'

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
}: CosyVoiceDeleteVoiceDialogProps) => {
  const { t } = useTranslation()
  return (
  <Dialog
    open={Boolean(pendingDeleteVoice)}
    onClose={onClose}
    fullWidth
    maxWidth="xs"
  >
    <DialogTitle>{t('audiobook.cosyVoiceDeleteVoiceDialog.title')}</DialogTitle>
    <DialogContent dividers>
      <Typography variant="body2">
        {t('audiobook.cosyVoiceDeleteVoiceDialog.confirmMessage', { label: pendingDeleteVoice?.label || '' })}
      </Typography>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={Boolean(cloneDeletingId)}>
        {t('action.cancel')}
      </Button>
      <Button
        color="error"
        variant="contained"
        onClick={onConfirm}
        disabled={Boolean(cloneDeletingId)}
      >
        {t('audiobook.cosyVoiceDeleteVoiceDialog.delete')}
      </Button>
    </DialogActions>
  </Dialog>
  )
}

export default CosyVoiceDeleteVoiceDialog
