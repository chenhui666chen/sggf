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
      <DialogTitle>重生成素材：{title}</DialogTitle>
      <DialogContent dividers>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {imageEditActive
            ? '图像编辑模式：将基于参考图生成，提交后状态变为“待审核”。'
            : '可在下方编辑提示词并重生成素材，生成后将变为待审核状态。'}
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
            {suggesting ? '提示词生成中…' : '智能生成提示词'}
          </Button>
          {forceImageEdit ? (
            <Chip size="small" color="secondary" variant="outlined" label="图像编辑：强制" />
          ) : (
            <Button
              size="small"
              variant={imageEditActive ? 'contained' : 'outlined'}
              color={imageEditActive ? 'secondary' : 'primary'}
              aria-pressed={imageEditActive}
              onClick={onToggleImageEdit}
              disabled={!canToggleImageEdit}
            >
              {imageEditActive ? '图像编辑：开启' : '使用图像编辑'}
            </Button>
          )}
        </Stack>
        {forceImageEdit && (
          <Alert severity={hasImageBase ? 'info' : 'error'} sx={{ mb: 1 }}>
            <Typography variant="body2">
              {hasImageBase
                ? `参考基底：${imageBaseLabel}。${
                    readyReferenceLabel
                      ? `参考图已就绪：${readyReferenceLabel}${
                          readyReferenceCount > 1
                            ? '（生成时将自动上传；额外参考图在模型支持多参考时生效）。'
                            : '（生成时将自动上传）。'
                        }`
                      : '参考图已就绪。'
                  }`
                : `缺少参考图：${missingReferenceLabel || '前序视角'}。请先生成前序视角。`}
            </Typography>
          </Alert>
        )}
        {!forceImageEdit && !hasImageBase && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            当前素材没有可编辑底图，将回退到文生图模式。
          </Typography>
        )}
        {suggestError && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {suggestError}
          </Alert>
        )}
        {imageEditActive && imageEditAutoCleared && (
          <Typography variant="caption" color="text.disabled" display="block" sx={{ mb: 1 }}>
            已清空原提示词，请填写本次需要修改的内容。
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
          取消
        </Button>
        <Button
          variant="contained"
          onClick={onSubmit}
          disabled={submitDisabled}
        >
          {submitting
            ? '生成中…'
            : imageEditActive
              ? '开始生成（图像编辑）'
              : '开始生成（提示词）'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

