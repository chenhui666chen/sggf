import type { ReactNode } from 'react'

import { useTranslation } from 'react-i18next'

import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from '@mui/material'

type DreamweaverPromptEditDialogContentProps = {
  shotDescription?: string | null
  headPrompt: string
  tailPrompt: string
  generatedPrompt: string
  videoPrompt: string
  saving: boolean
  error?: string | null
  onChangeHead: (value: string) => void
  onChangeTail: (value: string) => void
  onChangeVideo: (value: string) => void
}

export function DreamweaverPromptEditDialogContent({
  shotDescription,
  headPrompt,
  tailPrompt,
  generatedPrompt,
  videoPrompt,
  saving,
  error,
  onChangeHead,
  onChangeTail,
  onChangeVideo,
}: DreamweaverPromptEditDialogContentProps) {
  const { t } = useTranslation()
  return (
    <DialogContent dividers>
      {shotDescription && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {t('dreamweaverRun.promptShotDescription', { desc: shotDescription || '-' })}
        </Typography>
      )}
      <Stack spacing={1.5}>
        <TextField
          label={t('dreamweaverRun.promptHeadLabel')}
          fullWidth
          multiline
          minRows={3}
          value={headPrompt}
          onChange={(e) => onChangeHead(e.target.value)}
          disabled={saving}
        />
        <TextField
          label={t('dreamweaverRun.promptTailLabel')}
          fullWidth
          multiline
          minRows={3}
          value={tailPrompt}
          onChange={(e) => onChangeTail(e.target.value)}
          disabled={saving}
        />
        <TextField
          label={t('dreamweaverRun.promptVideoAutoLabel')}
          fullWidth
          multiline
          minRows={3}
          value={generatedPrompt}
          InputProps={{ readOnly: true }}
        />
        <TextField
          label={t('dreamweaverRun.promptVideoOverrideLabel')}
          fullWidth
          multiline
          minRows={3}
          value={videoPrompt}
          onChange={(e) => onChangeVideo(e.target.value)}
          disabled={saving}
          placeholder={t('dreamweaverRun.promptVideoOverridePlaceholder')}
        />
      </Stack>
      {error && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}
    </DialogContent>
  )
}

type DreamweaverPromptEditDialogActionsProps = {
  saving: boolean
  onClose: () => void
  onSave: () => void
}

export function DreamweaverPromptEditDialogActions({
  saving,
  onClose,
  onSave,
}: DreamweaverPromptEditDialogActionsProps) {
  const { t } = useTranslation()
  return (
    <DialogActions>
      <Button onClick={onClose} disabled={saving}>
        {t('common.cancel')}
      </Button>
      <Button variant="contained" onClick={onSave} disabled={saving}>
        {saving ? t('dreamweaverRun.promptEditSaving') : t('common.save')}
      </Button>
    </DialogActions>
  )
}

type DreamweaverPromptEditDialogShellProps = {
  open: boolean
  onClose: () => void
  title: string
  content: ReactNode
  actions: ReactNode
}

export function DreamweaverPromptEditDialogShell({
  open,
  onClose,
  title,
  content,
  actions,
}: DreamweaverPromptEditDialogShellProps) {
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{title}</DialogTitle>
      {content}
      {actions}
    </Dialog>
  )
}

type DreamweaverRegenerateDialogModeControlsProps = {
  suggesting: boolean
  submitting: boolean
  hasRole: boolean
  forceImageEdit: boolean
  imageEditActive: boolean
  hasImageBase: boolean
  onSmartGenerate: () => void
  onToggleImageEdit: () => void
}

export function DreamweaverRegenerateDialogModeControls({
  suggesting,
  submitting,
  hasRole,
  forceImageEdit,
  imageEditActive,
  hasImageBase,
  onSmartGenerate,
  onToggleImageEdit,
}: DreamweaverRegenerateDialogModeControlsProps) {
  const { t } = useTranslation()
  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap">
      <Button
        size="small"
        variant="outlined"
        onClick={onSmartGenerate}
        disabled={submitting || suggesting || !hasRole}
      >
        {suggesting ? t('dreamweaverRun.promptSuggesting') : t('dreamweaverRun.promptSmartGenerate')}
      </Button>
      {forceImageEdit ? (
        <Alert severity="info" sx={{ py: 0, px: 1 }}>
          {t('dreamweaverRun.promptImageEditForced')}
        </Alert>
      ) : (
        <Button
          size="small"
          variant={imageEditActive ? 'contained' : 'outlined'}
          color={imageEditActive ? 'secondary' : 'primary'}
          aria-pressed={imageEditActive}
          onClick={onToggleImageEdit}
          disabled={submitting || suggesting || !hasImageBase}
        >
          {imageEditActive ? t('dreamweaverRun.promptImageEditOn') : t('dreamweaverRun.promptUseImageEdit')}
        </Button>
      )}
    </Stack>
  )
}

type DreamweaverRegenerateDialogContentProps = {
  modeHint: string
  modeControls: ReactNode
  statusHints?: ReactNode
  promptInputLabel: string
  prompt: string
  promptPlaceholder?: string
  submitting: boolean
  suggesting: boolean
  error?: string | null
  onChangePrompt: (value: string) => void
}

export function DreamweaverRegenerateDialogContent({
  modeHint,
  modeControls,
  statusHints,
  promptInputLabel,
  prompt,
  promptPlaceholder,
  submitting,
  suggesting,
  error,
  onChangePrompt,
}: DreamweaverRegenerateDialogContentProps) {
  return (
    <DialogContent dividers>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        {modeHint}
      </Typography>
      {modeControls}
      {statusHints ?? null}
      <TextField
        label={promptInputLabel}
        fullWidth
        multiline
        minRows={8}
        value={prompt}
        placeholder={promptPlaceholder}
        onChange={(e) => onChangePrompt(e.target.value)}
        disabled={submitting || suggesting}
      />
      {error && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}
    </DialogContent>
  )
}

type DreamweaverRegenerateDialogActionsProps = {
  submitting: boolean
  submitLabel: string
  submitDisabled: boolean
  onClose: () => void
  onSubmit: () => void
}

export function DreamweaverRegenerateDialogActions({
  submitting,
  submitLabel,
  submitDisabled,
  onClose,
  onSubmit,
}: DreamweaverRegenerateDialogActionsProps) {
  const { t } = useTranslation()
  return (
    <DialogActions>
      <Button onClick={onClose} disabled={submitting}>
        {t('common.cancel')}
      </Button>
      <Button variant="contained" onClick={onSubmit} disabled={submitDisabled}>
        {submitLabel}
      </Button>
    </DialogActions>
  )
}

type DreamweaverRegenerateDialogShellProps = {
  open: boolean
  onClose: () => void
  title: string
  content: ReactNode
  actions: ReactNode
}

export function DreamweaverRegenerateDialogShell({
  open,
  onClose,
  title,
  content,
  actions,
}: DreamweaverRegenerateDialogShellProps) {
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{title}</DialogTitle>
      {content}
      {actions}
    </Dialog>
  )
}

type DreamweaverRegenerateDialogStatusHintsProps = {
  forceImageEdit: boolean
  hasImageBase: boolean
  alertBaseLabel: string
  alertReadyReferenceLabel: string
  alertReadyReferenceCount: number
  alertMissingReferenceLabel: string
  suggestError?: string | null
  imageEditActive: boolean
  imageEditAutoCleared: boolean
}

export function DreamweaverRegenerateDialogStatusHints({
  forceImageEdit,
  hasImageBase,
  alertBaseLabel,
  alertReadyReferenceLabel,
  alertReadyReferenceCount,
  alertMissingReferenceLabel,
  suggestError,
  imageEditActive,
  imageEditAutoCleared,
}: DreamweaverRegenerateDialogStatusHintsProps) {
  const { t } = useTranslation()
  return (
    <>
      {forceImageEdit && (
        <Alert severity={hasImageBase ? 'info' : 'error'} sx={{ mb: 1 }}>
          <Typography variant="body2">
            {hasImageBase
              ? `${t('dreamweaverRun.promptReferenceBase', { label: alertBaseLabel })} ${
                  alertReadyReferenceLabel
                    ? `${t('dreamweaverRun.promptReferenceReady', {
                        label: alertReadyReferenceLabel,
                        note:
                          alertReadyReferenceCount > 1
                            ? t('dreamweaverRun.promptReferenceMultiNote')
                            : t('dreamweaverRun.promptReferenceSingleNote'),
                      })}`
                    : t('dreamweaverRun.promptReferenceReadyNone')
                }`
              : t('dreamweaverRun.promptMissingReference', {
                  label: alertMissingReferenceLabel || t('dreamweaverRun.promptPreviousView'),
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
    </>
  )
}

type DreamweaverPromptEditDialogProps = {
  open: boolean
  onClose: () => void
  shotTitle: string
  shotDescription?: string | null
  headPrompt: string
  tailPrompt: string
  generatedPrompt: string
  videoPrompt: string
  saving: boolean
  error?: string | null
  onChangeHead: (value: string) => void
  onChangeTail: (value: string) => void
  onChangeVideo: (value: string) => void
  onSave: () => void
}

export function DreamweaverPromptEditDialog({
  open,
  onClose,
  shotTitle,
  shotDescription,
  headPrompt,
  tailPrompt,
  generatedPrompt,
  videoPrompt,
  saving,
  error,
  onChangeHead,
  onChangeTail,
  onChangeVideo,
  onSave,
}: DreamweaverPromptEditDialogProps) {
  const { t } = useTranslation()
  return (
    <DreamweaverPromptEditDialogShell
      open={open}
      onClose={onClose}
      title={t('dreamweaverRun.promptReviewTitle', { title: shotTitle })}
      content={
        <DreamweaverPromptEditDialogContent
          shotDescription={shotDescription}
          headPrompt={headPrompt}
          tailPrompt={tailPrompt}
          generatedPrompt={generatedPrompt}
          videoPrompt={videoPrompt}
          saving={saving}
          error={error}
          onChangeHead={onChangeHead}
          onChangeTail={onChangeTail}
          onChangeVideo={onChangeVideo}
        />
      }
      actions={<DreamweaverPromptEditDialogActions saving={saving} onClose={onClose} onSave={onSave} />}
    />
  )
}

type DreamweaverRegenerateDialogProps = {
  open: boolean
  onClose: () => void
  title: string
  modeHint: string
  suggesting: boolean
  submitting: boolean
  hasRole: boolean
  forceImageEdit: boolean
  imageEditActive: boolean
  hasImageBase: boolean
  alertBaseLabel: string
  alertReadyReferenceLabel: string
  alertReadyReferenceCount: number
  alertMissingReferenceLabel: string
  suggestError?: string | null
  imageEditAutoCleared: boolean
  promptInputLabel: string
  prompt: string
  promptPlaceholder?: string
  error?: string | null
  submitLabel: string
  submitDisabled: boolean
  onSmartGenerate: () => void
  onToggleImageEdit: () => void
  onChangePrompt: (value: string) => void
  onSubmit: () => void
}

export function DreamweaverRegenerateDialog({
  open,
  onClose,
  title,
  modeHint,
  suggesting,
  submitting,
  hasRole,
  forceImageEdit,
  imageEditActive,
  hasImageBase,
  alertBaseLabel,
  alertReadyReferenceLabel,
  alertReadyReferenceCount,
  alertMissingReferenceLabel,
  suggestError,
  imageEditAutoCleared,
  promptInputLabel,
  prompt,
  promptPlaceholder,
  error,
  submitLabel,
  submitDisabled,
  onSmartGenerate,
  onToggleImageEdit,
  onChangePrompt,
  onSubmit,
}: DreamweaverRegenerateDialogProps) {
  return (
    <DreamweaverRegenerateDialogShell
      open={open}
      onClose={onClose}
      title={title}
      content={
        <DreamweaverRegenerateDialogContent
          modeHint={modeHint}
          modeControls={
            <DreamweaverRegenerateDialogModeControls
              suggesting={suggesting}
              submitting={submitting}
              hasRole={hasRole}
              forceImageEdit={forceImageEdit}
              imageEditActive={imageEditActive}
              hasImageBase={hasImageBase}
              onSmartGenerate={onSmartGenerate}
              onToggleImageEdit={onToggleImageEdit}
            />
          }
          statusHints={
            <DreamweaverRegenerateDialogStatusHints
              forceImageEdit={forceImageEdit}
              hasImageBase={hasImageBase}
              alertBaseLabel={alertBaseLabel}
              alertReadyReferenceLabel={alertReadyReferenceLabel}
              alertReadyReferenceCount={alertReadyReferenceCount}
              alertMissingReferenceLabel={alertMissingReferenceLabel}
              suggestError={suggestError}
              imageEditActive={imageEditActive}
              imageEditAutoCleared={imageEditAutoCleared}
            />
          }
          promptInputLabel={promptInputLabel}
          prompt={prompt}
          promptPlaceholder={promptPlaceholder}
          submitting={submitting}
          suggesting={suggesting}
          error={error}
          onChangePrompt={onChangePrompt}
        />
      }
      actions={
        <DreamweaverRegenerateDialogActions
          submitting={submitting}
          submitLabel={submitLabel}
          submitDisabled={submitDisabled}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      }
    />
  )
}
