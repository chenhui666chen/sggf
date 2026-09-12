import {
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import type { Chapter, DreamweaverProjectLockedGenerationConfig } from '@/types/dreamweaver'
import {
  IMAGE_MODEL_OPTIONS,
  IMAGE_RATIOS_LABELS,
  IMAGE_RESOLUTIONS_LABELS,
  STYLE_PRESET_LABELS,
  VIDEO_EDIT_MODEL_OPTIONS,
  VIDEO_MODEL_OPTIONS,
  VISION_MODEL_OPTIONS,
} from '@/constants/dreamweaver'
import { useTranslation } from 'react-i18next'

interface ConfigPanelProps {
  open: boolean
  onClose: () => void
  onRun: () => Promise<boolean>
  running: boolean
  chapters: Chapter[]
  selectedChapterIds: number[]
  onToggleChapter: (id: number) => void
  onSelectAll: () => void
  highQuality: boolean
  onQualityChange: (high: boolean) => void
  qcAllowFail: boolean
  onQcAllowFailChange: (v: boolean) => void
  smartTuning: boolean
  onSmartTuningChange: (v: boolean) => void
  abVariant: string
  onAbVariantChange: (v: string) => void
  videoRequireConfirmation: boolean
  onVideoRequireConfirmationChange: (v: boolean) => void
  promptReviewRequired: boolean
  onPromptReviewRequiredChange: (v: boolean) => void
  stylePreset: string
  onStylePresetChange: (v: string) => void
  imageRatio: string
  onImageRatioChange: (v: string) => void
  imageResolution: string
  onImageResolutionChange: (v: string) => void
  imageModel: string
  onImageModelChange: (v: string) => void
  videoModel: string
  onVideoModelChange: (v: string) => void
  videoEditModel: string
  onVideoEditModelChange: (v: string) => void
  visionModel: string
  onVisionModelChange: (v: string) => void
  enableVideoEdit: boolean
  onEnableVideoEditChange: (v: boolean) => void
  enableVisionReview: boolean
  onEnableVisionReviewChange: (v: boolean) => void
  lockedConfig: DreamweaverProjectLockedGenerationConfig | null
  lockedConfigError: string | null
}

const STYLE_PRESET_OPTIONS = Object.keys(STYLE_PRESET_LABELS).map((value) => ({ value, label: STYLE_PRESET_LABELS[value] }))

const IMAGE_RATIO_OPTIONS = Object.keys(IMAGE_RATIOS_LABELS).map((value) => ({ value, label: IMAGE_RATIOS_LABELS[value] }))

const IMAGE_RESOLUTION_OPTIONS = Object.keys(IMAGE_RESOLUTIONS_LABELS).map((value) => ({ value, label: IMAGE_RESOLUTIONS_LABELS[value] }))

export function ConfigPanel({
  open,
  onClose,
  onRun,
  running,
  chapters,
  selectedChapterIds,
  onToggleChapter,
  onSelectAll,
  highQuality,
  onQualityChange,
  qcAllowFail,
  onQcAllowFailChange,
  smartTuning,
  onSmartTuningChange,
  abVariant,
  onAbVariantChange,
  videoRequireConfirmation,
  onVideoRequireConfirmationChange,
  promptReviewRequired,
  onPromptReviewRequiredChange,
  stylePreset,
  onStylePresetChange,
  imageRatio,
  onImageRatioChange,
  imageResolution,
  onImageResolutionChange,
  imageModel,
  onImageModelChange,
  videoModel,
  onVideoModelChange,
  videoEditModel,
  onVideoEditModelChange,
  visionModel,
  onVisionModelChange,
  enableVideoEdit,
  onEnableVideoEditChange,
  enableVisionReview,
  onEnableVisionReviewChange,
  lockedConfig,
  lockedConfigError,
}: ConfigPanelProps) {
  const { t } = useTranslation()
  const isLocked = lockedConfig?.locked ?? false
  const allSelected = chapters.length > 0 && selectedChapterIds.length === chapters.length

  const handleRun = async () => {
    const success = await onRun()
    if (success) {
      onClose()
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Typography variant="h6">{t('dreamweaverRun.configTitle')}</Typography>
          <IconButton onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Stack>
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={3}>
          {lockedConfigError && (
            <Typography color="error" variant="body2">
              {lockedConfigError}
            </Typography>
          )}

          {isLocked && (
            <Paper variant="outlined" sx={{ p: 2, bgcolor: 'warning.lighter' }}>
              <Typography variant="body2" color="warning.dark">
                {t('dreamweaverRun.configLockedNotice')}
              </Typography>
            </Paper>
          )}

          <Box>
            <Typography variant="subtitle2" gutterBottom>
              {t('dreamweaverRun.configChapterSection')}
            </Typography>
            <Paper variant="outlined" sx={{ p: 1, maxHeight: 200, overflow: 'auto' }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  {t('dreamweaverRun.configSelectedCount', { selected: selectedChapterIds.length, total: chapters.length })}
                </Typography>
                <Button size="small" onClick={onSelectAll}>
                  {t(allSelected ? 'dreamweaverRun.configDeselectAll' : 'dreamweaverRun.configSelectAll')}
                </Button>
              </Stack>
              <Divider sx={{ my: 1 }} />
              <Grid container spacing={1}>
                {chapters.map((chapter) => (
                  <Grid item xs={12} sm={6} md={4} key={chapter.id}>
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={selectedChapterIds.includes(chapter.id)}
                          onChange={() => onToggleChapter(chapter.id)}
                          size="small"
                        />
                      }
                      label={
                        <Typography variant="body2" noWrap>
                          {t('dreamweaverRun.configChapterItem', { number: chapter.chapter_number, title: chapter.title })}
                        </Typography>
                      }
                    />
                  </Grid>
                ))}
              </Grid>
            </Paper>
          </Box>

          <Box>
            <Typography variant="subtitle2" gutterBottom>
              {t('dreamweaverRun.configQualitySection')}
            </Typography>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>{t('dreamweaverRun.configQualityMode')}</InputLabel>
                    <Select
                      value={highQuality ? 'quality' : 'cost'}
                      label={t('dreamweaverRun.configQualityMode')}
                      onChange={(e) => onQualityChange(e.target.value === 'quality')}
                      disabled={isLocked && lockedConfig?.quality_mode != null}
                    >
                      <MenuItem value="quality">{t('dreamweaverRun.configQualityHigh')}</MenuItem>
                      <MenuItem value="cost">{t('dreamweaverRun.configQualityCost')}</MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>{t('dreamweaverRun.regenStylePresetLabel')}</InputLabel>
                    <Select
                      value={stylePreset}
                      label={t('dreamweaverRun.regenStylePresetLabel')}
                      onChange={(e) => onStylePresetChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.style_preset != null}
                    >
                      {STYLE_PRESET_OPTIONS.map((preset) => (
                        <MenuItem key={preset.value} value={preset.value}>
                          {t(preset.label)}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>{t('dreamweaverRun.regenImageRatioLabel')}</InputLabel>
                    <Select
                      value={imageRatio}
                      label={t('dreamweaverRun.regenImageRatioLabel')}
                      onChange={(e) => onImageRatioChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.image_ratio != null}
                    >
                      {IMAGE_RATIO_OPTIONS.map((ratio) => (
                        <MenuItem key={ratio.value} value={ratio.value}>
                          {t(ratio.label)}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>{t('dreamweaverRun.configImageResolution')}</InputLabel>
                    <Select
                      value={imageResolution}
                      label={t('dreamweaverRun.configImageResolution')}
                      onChange={(e) => onImageResolutionChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.image_resolution != null}
                    >
                      {IMAGE_RESOLUTION_OPTIONS.map((res) => (
                        <MenuItem key={res.value} value={res.value}>
                          {t(res.label)}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>{t('dreamweaverRun.configImageModel')}</InputLabel>
                    <Select
                      value={imageModel}
                      label={t('dreamweaverRun.configImageModel')}
                      onChange={(e) => onImageModelChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.image_model != null}
                    >
                      {IMAGE_MODEL_OPTIONS.map((model) => (
                        <MenuItem key={model.value} value={model.value}>
                          {t(model.label)}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>{t('dreamweaverRun.configVideoModel')}</InputLabel>
                    <Select
                      value={videoModel}
                      label={t('dreamweaverRun.configVideoModel')}
                      onChange={(e) => onVideoModelChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.video_model != null}
                    >
                      {VIDEO_MODEL_OPTIONS.map((model) => (
                        <MenuItem key={model.value} value={model.value}>
                          {t(model.label)}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
              </Grid>
            </Paper>
          </Box>

          <Box>
            <Typography variant="subtitle2" gutterBottom>
              {t('dreamweaverRun.configModelSection')}
            </Typography>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={enableVisionReview}
                        onChange={(e) => onEnableVisionReviewChange(e.target.checked)}
                        disabled={isLocked && lockedConfig?.enable_vision_review != null}
                      />
                    }
                    label={t('dreamweaverRun.configEnableVisionReview')}
                  />
                  {enableVisionReview && (
                    <FormControl fullWidth size="small" sx={{ mt: 1 }}>
                      <InputLabel>{t('dreamweaverRun.configVisionModel')}</InputLabel>
                      <Select
                        value={visionModel}
                        label={t('dreamweaverRun.configVisionModel')}
                        onChange={(e) => onVisionModelChange(e.target.value)}
                        disabled={isLocked && lockedConfig?.vision_model != null}
                      >
                        {VISION_MODEL_OPTIONS.map((model) => (
                          <MenuItem key={model.value} value={model.value}>
                            {t(model.label)}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  )}
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={enableVideoEdit}
                        onChange={(e) => onEnableVideoEditChange(e.target.checked)}
                        disabled={isLocked && lockedConfig?.enable_video_edit != null}
                      />
                    }
                    label={t('dreamweaverRun.configEnableVideoEdit')}
                  />
                  {enableVideoEdit && (
                    <FormControl fullWidth size="small" sx={{ mt: 1 }}>
                      <InputLabel>{t('dreamweaverRun.configVideoEditModel')}</InputLabel>
                      <Select
                        value={videoEditModel}
                        label={t('dreamweaverRun.configVideoEditModel')}
                        onChange={(e) => onVideoEditModelChange(e.target.value)}
                        disabled={isLocked && lockedConfig?.video_edit_model != null}
                      >
                        {VIDEO_EDIT_MODEL_OPTIONS.map((model) => (
                          <MenuItem key={model.value} value={model.value}>
                            {t(model.label)}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  )}
                </Grid>
                <Grid item xs={12}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                    {t('dreamweaverRun.configVisionVideoEditHint')}
                  </Typography>
                </Grid>
              </Grid>
            </Paper>
          </Box>

          <Box>
            <Typography variant="subtitle2" gutterBottom>
              {t('dreamweaverRun.configAdvancedSection')}
            </Typography>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={smartTuning}
                        onChange={(e) => onSmartTuningChange(e.target.checked)}
                        disabled={isLocked && lockedConfig?.smart_tuning != null}
                      />
                    }
                    label={t('dreamweaverRun.strategyTitleSmartTuning')}
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={videoRequireConfirmation}
                        onChange={(e) => onVideoRequireConfirmationChange(e.target.checked)}
                        disabled={isLocked && lockedConfig?.video_require_confirmation != null}
                      />
                    }
                    label={t('dreamweaverRun.strategyTitleVideoConfirmation')}
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={promptReviewRequired}
                        onChange={(e) => onPromptReviewRequiredChange(e.target.checked)}
                        disabled={isLocked && lockedConfig?.prompt_review_required != null}
                      />
                    }
                    label={t('dreamweaverRun.strategyTitlePromptReview')}
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={qcAllowFail}
                        onChange={(e) => onQcAllowFailChange(e.target.checked)}
                      />
                    }
                    label={t('dreamweaverRun.strategyTitleQcFail')}
                  />
                </Grid>
                <Grid item xs={12}>
                  <TextField
                    fullWidth
                    size="small"
                    label={t('dreamweaverRun.configAbVariant')}
                    value={abVariant}
                    onChange={(e) => onAbVariantChange(e.target.value)}
                    placeholder={t('dreamweaverRun.configAbVariantPlaceholder')}
                  />
                </Grid>
              </Grid>
            </Paper>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button
          variant="contained"
          startIcon={<PlayArrowIcon />}
          onClick={handleRun}
          disabled={running || selectedChapterIds.length === 0}
        >
          {t(running ? 'dreamweaverRun.configStarting' : 'dreamweaverRun.configStartGenerating')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
