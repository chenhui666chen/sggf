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
  })
  const {
    hasDelta,
  } = dialogView
  const dialogLocked = loading || Boolean(confirmDialog)

  return (
    <>
      <Dialog open={open} onClose={dialogLocked ? undefined : handlers.onClose} maxWidth="sm" fullWidth>
        <DialogTitle>协同扩展</DialogTitle>
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
            取消
          </Button>
          <Button onClick={handlers.onConfirm} variant="contained" disabled={!hasDelta || dialogLocked}>
            {loading ? '协同扩展中...' : '开始协同扩展'}
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
            <AlertTitle>影响范围</AlertTitle>
            {confirmDialog?.detail}
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={onConfirmDialogClose}>
            {confirmDialog?.cancelLabel ?? '取消'}
          </Button>
          <Button onClick={onConfirmDialogConfirm} variant="contained" color="warning" autoFocus>
            {confirmDialog?.confirmLabel ?? '继续'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
