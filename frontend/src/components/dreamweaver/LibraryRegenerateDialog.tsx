import type { ReactNode } from 'react'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

interface LibraryRegenerateDialogProps {
  open: boolean
  title: string
  role: string
  submitting: boolean
  suggesting: boolean
  imageEditActive: boolean
  forceImageEdit: boolean
  hasImageBase: boolean
  imageBaseLabel: string
  readyReferenceLabel: string
  readyReferenceCount: number
  missingReferenceLabel: string
  imageEditAutoCleared: boolean
  promptInputLabel: string
  promptValue: string
  promptPlaceholder?: string
  suggestError?: string | null
  error?: string | null
  submitDisabled: boolean
  suggestDisabled: boolean
  canToggleImageEdit: boolean
  onClose: () => void
  onSuggest: () => void
  onToggleImageEdit: () => void
  onPromptChange: (value: string) => void
  onSubmit: () => void
  showDerivedViewHint?: boolean
  derivedViewHintText?: string
  lockedInfoText?: string
  extraSettings?: ReactNode
}

export default function LibraryRegenerateDialog(props: LibraryRegenerateDialogProps) {
  const { t } = useTranslation()
  const {
    open,
    title,
    submitting,
    suggesting,
    imageEditActive,
    forceImageEdit,
    hasImageBase,
    imageBaseLabel,
    readyReferenceLabel,
    readyReferenceCount,
    missingReferenceLabel,
    imageEditAutoCleared,
    promptInputLabel,
    promptValue,
    promptPlaceholder,
    suggestError,
    error,
    submitDisabled,
    suggestDisabled,
    canToggleImageEdit,
    onClose,
    onSuggest,
    onToggleImageEdit,
    onPromptChange,
    onSubmit,
    showDerivedViewHint,
    derivedViewHintText,
    lockedInfoText,
    extraSettings,
  } = props

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (submitting) return
        onClose()
      }}
      fullWidth
      maxWidth="md"
    >
      <DialogTitle>{t('dreamweaverRun.regenerateAsset', { title })}</DialogTitle>
      <DialogContent dividers>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {imageEditActive
            ? t('dreamweaverRun.regenModeHintImageEdit')
            : t('dreamweaverRun.regenModeHintTextEdit')}
        </Typography>
        {showDerivedViewHint && derivedViewHintText && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            {derivedViewHintText}
          </Typography>
        )}
        {lockedInfoText && (
          <Alert severity="info" sx={{ mb: 1 }}>
            {lockedInfoText}
          </Alert>
        )}
        {extraSettings}
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap">
          <Button
            size="small"
            variant="outlined"
            onClick={onSuggest}
            disabled={suggestDisabled}
          >
            {suggesting ? t('dreamweaverRun.promptSuggesting') : t('dreamweaverRun.promptSmartGenerate')}
          </Button>
          {forceImageEdit ? (
            <Chip size="small" color="secondary" variant="outlined" label={t('dreamweaverRun.promptImageEditForced')} />
          ) : (
            <Button
              size="small"
              variant={imageEditActive ? 'contained' : 'outlined'}
              color={imageEditActive ? 'secondary' : 'primary'}
              aria-pressed={imageEditActive}
              onClick={onToggleImageEdit}
              disabled={!canToggleImageEdit}
            >
              {imageEditActive ? t('dreamweaverRun.promptImageEditOn') : t('dreamweaverRun.promptUseImageEdit')}
            </Button>
          )}
        </Stack>
        {forceImageEdit && (
          <Alert severity={hasImageBase ? 'info' : 'error'} sx={{ mb: 1 }}>
            <Typography variant="body2">
              {hasImageBase
                ? `${t('dreamweaverRun.promptReferenceBase', { label: imageBaseLabel })} ${
                    readyReferenceLabel
                      ? `${t('dreamweaverRun.promptReferenceReady', {
                          label: readyReferenceLabel,
                          note:
                            readyReferenceCount > 1
                              ? t('dreamweaverRun.promptReferenceMultiNote')
                              : t('dreamweaverRun.promptReferenceSingleNote'),
                        })}`
                      : t('dreamweaverRun.promptReferenceReadyNone')
                  }`
                : t('dreamweaverRun.promptMissingReference', {
                    label: missingReferenceLabel || t('dreamweaverRun.promptPreviousView'),
                  })}
            </Typography>
          </Alert>
        )}
        {!forceImageEdit && !hasImageBase && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            {t('dreamweaverRun.promptNoEditableBase')}
          </Typography>
        )}
        {suggestError && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {suggestError}
          </Alert>
        )}
        {imageEditActive && imageEditAutoCleared && (
          <Typography variant="caption" color="text.disabled" display="block" sx={{ mb: 1 }}>
            {t('dreamweaverRun.promptOverrideCleared')}
          </Typography>
        )}
        <TextField
          label={promptInputLabel}
          fullWidth
          multiline
          minRows={8}
          value={promptValue}
          placeholder={promptPlaceholder}
          onChange={(e) => onPromptChange(e.target.value)}
          disabled={submitting || suggesting}
        />
        {error && (
          <Alert severity="error" sx={{ mt: 1 }}>
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
          onClick={onSubmit}
          disabled={submitDisabled}
        >
          {submitting
            ? t('dreamweaverRun.regenSubmitGenerating')
            : imageEditActive
              ? t('dreamweaverRun.regenSubmitImageEdit')
              : t('dreamweaverRun.regenSubmitPrompt')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

