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
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
  const { open, assetRole, subjectId, submitting, error, onSubjectIdChange, onClose, onSubmit } = props

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t('dreamweaverRun.providerBindKlingTitle')}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t('dreamweaverRun.providerBindDescription')}
        </Typography>
        {/* 合规修订：素材同步/绑定可灵时的服务方提示 */}
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5, lineHeight: 1.7 }}>
          {t('dreamweaverRun.providerComplianceNotice')}
        </Typography>
        <TextField
          fullWidth
          size="small"
          label={t('dreamweaverRun.providerKlingSubjectIdLabel')}
          value={subjectId}
          onChange={(e) => onSubjectIdChange(e.target.value)}
          placeholder={t('dreamweaverRun.providerSubjectIdPlaceholder')}
          disabled={submitting}
          sx={{ mb: 1 }}
        />
        <Typography variant="caption" color="text.secondary">
          {t('dreamweaverRun.libraryRoleLabel', { title: assetRole })}
        </Typography>
        {error && (
          <Alert severity="error" sx={{ mt: 1, borderRadius: 2 }}>
            {error}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>
          {t('common.cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={() => void onSubmit()}
          disabled={submitting}
        >
          {submitting ? t('dreamweaverRun.providerBinding') : subjectId.trim() ? t('dreamweaverRun.providerBind') : t('dreamweaverRun.libraryUnbind')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
