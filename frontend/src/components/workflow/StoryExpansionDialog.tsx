import { useTranslation } from 'react-i18next'

import {
  Alert,
  AlertTitle,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Typography,
} from '@mui/material'
import type {
  StoryExpansionDialogContextState,
  StoryExpansionDialogFormState,
  StoryExpansionDialogHandlers,
} from '@/types/storyExpansionDialog'
import type { StoryExpansionConfirmDialogConfig } from '@/utils/storyExpansionSubmission'
import { createStoryExpansionDialogView } from '@/utils/storyExpansionDialogView'
import {
  StoryExpansionConfigSection,
  StoryExpansionPrecheckSection,
} from './StoryExpansionDialogSections'

export interface StoryExpansionDialogProps {
  open: boolean
  loading: boolean
  context: StoryExpansionDialogContextState
  form: StoryExpansionDialogFormState
  handlers: StoryExpansionDialogHandlers
  confirmDialog: StoryExpansionConfirmDialogConfig | null
  onConfirmDialogClose: () => void
  onConfirmDialogConfirm: () => void
}

export default function StoryExpansionDialog({
  open,
  loading,
  context,
  form,
  handlers,
  confirmDialog,
  onConfirmDialogClose,
  onConfirmDialogConfirm,
}: StoryExpansionDialogProps) {
  const { t } = useTranslation()
  const {
    analysis,
    analysisLoading,
    currentChapterCount,
    currentCharacterCount,
    recommendedMode,
  } = context
  const {
    targetChapterCount,
    targetCharacterCount,
    expansionMode,
    totalVolumes,
    totalChaptersMin,
    totalChaptersMax,
    frameworkMetadata,
    targetVolumeIndex,
    volumeChaptersMin,
    volumeChaptersMax,
    volumeCharacterIncrement,
    autoSupplementEnabled,
  } = form
  const dialogView = createStoryExpansionDialogView({
    currentChapterCount,
    currentCharacterCount,
    recommendedMode,
    targetChapterCount,
    targetCharacterCount,
    expansionMode,
    totalVolumes,
    totalChaptersMin,
    totalChaptersMax,
    frameworkMetadata,
    targetVolumeIndex,
    volumeChaptersMin,
    volumeChaptersMax,
    volumeCharacterIncrement,
    analysis,
  }, t)
  const {
    hasDelta,
  } = dialogView
  const dialogLocked = loading || Boolean(confirmDialog)

  return (
    <>
      <Dialog open={open} onClose={dialogLocked ? undefined : handlers.onClose} maxWidth="sm" fullWidth>
        <DialogTitle>{t('storyExpansion.dialog.title')}</DialogTitle>
        <DialogContent dividers>
          <StoryExpansionConfigSection
            form={form}
            handlers={handlers}
            view={dialogView}
          />

          <Divider sx={{ my: 2.5 }} />

          <StoryExpansionPrecheckSection
            analysisLoading={analysisLoading}
            autoSupplementEnabled={autoSupplementEnabled}
            view={dialogView}
          />

          {dialogView.validationMessage && !hasDelta && (
            <Typography variant="body2" color="error.main" sx={{ mt: 2.5 }}>
              {dialogView.validationMessage}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handlers.onClose} disabled={dialogLocked}>
            {t('action.cancel')}
          </Button>
          <Button onClick={handlers.onConfirm} variant="contained" disabled={!hasDelta || dialogLocked}>
            {loading ? t('storyExpansion.dialog.running') : t('storyExpansion.dialog.start')}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(confirmDialog)} onClose={onConfirmDialogClose} maxWidth="xs" fullWidth>
        <DialogTitle>{confirmDialog?.title}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body1">
            {confirmDialog?.description}
          </Typography>
          <Alert severity="warning" variant="outlined" sx={{ mt: 2 }}>
            <AlertTitle>{t('storyExpansion.dialog.impactTitle')}</AlertTitle>
            {confirmDialog?.detail}
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={onConfirmDialogClose}>
            {confirmDialog?.cancelLabel ?? t('action.cancel')}
          </Button>
          <Button onClick={onConfirmDialogConfirm} variant="contained" color="warning" autoFocus>
            {confirmDialog?.confirmLabel ?? t('storyExpansion.dialog.confirmContinue')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
