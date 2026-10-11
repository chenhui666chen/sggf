import {
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Typography,
} from '@mui/material'
import Close from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'

import PrivacyPolicyContent from '@/components/PrivacyPolicyContent'

interface PrivacyPolicyDialogProps {
  open: boolean
  onClose: () => void
}

/**
 * P2-5.5 修订：《隐私政策》页内弹窗。
 *
 * 在注册/第三方建号的同意勾选处就地弹出，读完关闭即回到原表单，
 * 避免新标签页打开导致用户已填写内容"丢失"的体验问题。
 */
export default function PrivacyPolicyDialog({ open, onClose }: PrivacyPolicyDialogProps) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md" scroll="paper">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', pb: 1.5 }}>
        <Typography variant="h6" fontWeight="bold">
          {t('privacyPolicyDialog.title')}
        </Typography>
        <IconButton aria-label={t('action.close')} onClick={onClose} size="small">
          <Close />
        </IconButton>
      </DialogTitle>
      <Divider />
      <DialogContent dividers sx={{ bgcolor: 'background.default' }}>
        <PrivacyPolicyContent />
      </DialogContent>
    </Dialog>
  )
}
