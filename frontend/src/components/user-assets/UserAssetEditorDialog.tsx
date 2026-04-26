import SaveIcon from '@mui/icons-material/Save'
import {
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
} from '@mui/material'

import {
  buildUserAssetEditorDialogPresentation,
  type UserAssetEditorFormData,
} from './userAssetEditorPresentation'

export type UserAssetEditorDialogProps = {
  open: boolean
  formData: UserAssetEditorFormData
  submitting?: boolean
  hasAsset: boolean
  onClose: () => void
  onSave: () => void
  onFormDataChange: (updater: (prev: UserAssetEditorFormData) => UserAssetEditorFormData) => void
}

export default function UserAssetEditorDialog(props: UserAssetEditorDialogProps) {
  const {
    open,
    formData,
    submitting = false,
    hasAsset,
    onClose,
    onSave,
    onFormDataChange,
  } = props

  const presentation = buildUserAssetEditorDialogPresentation({
    submitting,
    hasAsset,
  })

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{presentation.dialogTitle}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            fullWidth
            required
            label={presentation.titleLabel}
            value={formData.title}
            onChange={(event) => onFormDataChange((prev) => ({ ...prev, title: event.target.value }))}
            disabled={submitting}
          />
          <TextField
            fullWidth
            multiline
            minRows={3}
            maxRows={6}
            label={presentation.descriptionLabel}
            value={formData.description}
            onChange={(event) => onFormDataChange((prev) => ({ ...prev, description: event.target.value }))}
            disabled={submitting}
          />
          <TextField
            fullWidth
            multiline
            minRows={2}
            maxRows={4}
            label={presentation.tagsLabel}
            placeholder={presentation.tagsPlaceholder}
            value={formData.tagsText}
            onChange={(event) => onFormDataChange((prev) => ({ ...prev, tagsText: event.target.value }))}
            helperText={presentation.tagsHelperText}
            disabled={submitting}
          />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 2 }}>
        <Button onClick={onClose} disabled={submitting}>
          {presentation.cancelLabel}
        </Button>
        <Button
          variant="contained"
          onClick={onSave}
          disabled={presentation.saveDisabled}
          startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
        >
          {submitting ? presentation.savingLabel : presentation.saveLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
