import {
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
}

export default function StoryExpansionDialog({
  open,
  loading,
  context,
  form,
  handlers,
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

  return (
    <Dialog open={open} onClose={loading ? undefined : handlers.onClose} maxWidth="sm" fullWidth>
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
        <Button onClick={handlers.onClose} disabled={loading}>
          取消
        </Button>
        <Button onClick={handlers.onConfirm} variant="contained" disabled={!hasDelta || loading}>
          {loading ? '协同扩展中...' : '开始协同扩展'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
