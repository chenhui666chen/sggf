import type { ReactNode } from 'react'

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
  return (
    <DialogContent dividers>
      {shotDescription && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          镜头描述：{shotDescription || '-'}
        </Typography>
      )}
      <Stack spacing={1.5}>
        <TextField
          label="首帧提示词"
          fullWidth
          multiline
          minRows={3}
          value={headPrompt}
          onChange={(e) => onChangeHead(e.target.value)}
          disabled={saving}
        />
        <TextField
          label="尾帧提示词"
          fullWidth
          multiline
          minRows={3}
          value={tailPrompt}
          onChange={(e) => onChangeTail(e.target.value)}
          disabled={saving}
        />
        <TextField
          label="视频提示词（自动）"
          fullWidth
          multiline
          minRows={3}
          value={generatedPrompt}
          InputProps={{ readOnly: true }}
        />
        <TextField
          label="视频提示词覆盖（可选）"
          fullWidth
          multiline
          minRows={3}
          value={videoPrompt}
          onChange={(e) => onChangeVideo(e.target.value)}
          disabled={saving}
          placeholder="留空则使用系统拼接的默认视频提示词"
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
  return (
    <DialogActions>
      <Button onClick={onClose} disabled={saving}>
        取消
      </Button>
      <Button variant="contained" onClick={onSave} disabled={saving}>
        {saving ? '保存中...' : '保存'}
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
  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap">
      <Button
        size="small"
        variant="outlined"
        onClick={onSmartGenerate}
        disabled={submitting || suggesting || !hasRole}
      >
        {suggesting ? '提示词生成中...' : '智能生成提示词'}
      </Button>
      {forceImageEdit ? (
        <Alert severity="info" sx={{ py: 0, px: 1 }}>
          图像编辑：强制
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
          {imageEditActive ? '图像编辑：开启' : '使用图像编辑'}
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
  return (
    <DialogActions>
      <Button onClick={onClose} disabled={submitting}>
        取消
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
