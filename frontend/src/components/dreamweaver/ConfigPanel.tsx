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

const STYLE_PRESET_OPTIONS = [
  { value: 'cinematic_realistic', label: '电影写实' },
  { value: 'anime', label: '动漫风格' },
  { value: 'ink_wash', label: '水墨风格' },
  { value: 'cyberpunk', label: '赛博朋克' },
]

const IMAGE_RATIO_OPTIONS = [
  { value: '16:9', label: '横屏 16:9' },
  { value: '9:16', label: '竖屏 9:16' },
]

const IMAGE_RESOLUTION_OPTIONS = [
  { value: '720p', label: '高清 720p' },
  { value: '1080p', label: '全高清 1080p' },
]

const IMAGE_MODEL_OPTIONS = [
  { value: 'wan2.6-t2i', label: 'Wan 2.6 T2I（主力文生图）' },
  { value: 'qwen-image-2.0', label: 'Qwen Image 2.0' },
  { value: 'qwen-image-2.0-pro', label: 'Qwen Image 2.0 Pro（旗舰）' },
  { value: 'wan2.7-image', label: 'Wan 2.7 Image' },
  { value: 'doubao-seedream-4-5', label: 'Doubao Seedream 4.5' },
  { value: 'doubao-seedream-5-0', label: 'Doubao Seedream 5.0（最新）' },
  { value: 'kling-v3-image-generation', label: 'Kling V3 图像生成' },
  { value: 'kling-v3-omni-image-generation', label: 'Kling V3 Omni 图像生成' },
  { value: 'qwen-image-edit-plus', label: 'Qwen Image Edit Plus（编辑）' },
]

const VIDEO_MODEL_OPTIONS = [
  { value: 'wan2.7-t2v', label: 'Wan 2.7 T2V（主力视频）' },
  { value: 'wan2.6-t2v-fast', label: 'Wan 2.6 T2V Fast（快速预览）' },
  { value: 'wan2.7-i2v', label: 'Wan 2.7 I2V（首帧驱动）' },
  { value: 'doubao-seedance-2-0', label: 'Doubao Seedance 2.0（SOTA）' },
  { value: 'doubao-seedance-2-0-fast', label: 'Doubao Seedance 2.0 Fast' },
  { value: 'doubao-seedance-1-5-pro', label: 'Doubao Seedance 1.5 Pro' },
  { value: 'kling-v3-video-generation', label: 'Kling V3（可灵）' },
  { value: 'kling-v3-omni-video-generation', label: 'Kling V3 Omni（全能）' },
  { value: 'pixverse-v6-t2v', label: 'PixVerse V6' },
  { value: 'vidu-q3-pro-text2video', label: 'Vidu Q3 Pro 文生视频' },
  { value: 'vidu-q3-pro-img2video', label: 'Vidu Q3 Pro 图生视频' },
  { value: 'vidu-q3-pro-start-end2video', label: 'Vidu Q3 Pro 首尾帧' },
]

const VIDEO_EDIT_MODEL_OPTIONS = [
  { value: 'wan2.7-videoedit', label: 'Wan 2.7 VideoEdit（万相编辑）' },
  { value: 'doubao-seedance-2-0', label: 'Doubao Seedance 2.0' },
  { value: 'kling-v3-video-generation', label: 'Kling V3' },
]

const VISION_MODEL_OPTIONS = [
  { value: 'qwen3-vl-plus', label: 'Qwen3-VL-Plus（视觉理解）' },
  { value: 'qwen3.5-omni-plus', label: 'Qwen3.5 Omni Plus（全能）' },
]

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
          <Typography variant="h6">生成配置</Typography>
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
                当前项目已锁定配置，部分选项不可修改
              </Typography>
            </Paper>
          )}

          <Box>
            <Typography variant="subtitle2" gutterBottom>
              章节选择
            </Typography>
            <Paper variant="outlined" sx={{ p: 1, maxHeight: 200, overflow: 'auto' }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  已选 {selectedChapterIds.length} / {chapters.length} 章
                </Typography>
                <Button size="small" onClick={onSelectAll}>
                  {allSelected ? '取消全选' : '全选'}
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
                          第{chapter.chapter_number}章: {chapter.title}
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
              质量设置
            </Typography>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>质量模式</InputLabel>
                    <Select
                      value={highQuality ? 'quality' : 'cost'}
                      label="质量模式"
                      onChange={(e) => onQualityChange(e.target.value === 'quality')}
                      disabled={isLocked && lockedConfig?.quality_mode != null}
                    >
                      <MenuItem value="quality">高质量（较慢）</MenuItem>
                      <MenuItem value="cost">经济模式（较快）</MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>风格预设</InputLabel>
                    <Select
                      value={stylePreset}
                      label="风格预设"
                      onChange={(e) => onStylePresetChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.style_preset != null}
                    >
                      {STYLE_PRESET_OPTIONS.map((preset) => (
                        <MenuItem key={preset.value} value={preset.value}>
                          {preset.label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>图片比例</InputLabel>
                    <Select
                      value={imageRatio}
                      label="图片比例"
                      onChange={(e) => onImageRatioChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.image_ratio != null}
                    >
                      {IMAGE_RATIO_OPTIONS.map((ratio) => (
                        <MenuItem key={ratio.value} value={ratio.value}>
                          {ratio.label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>图片分辨率</InputLabel>
                    <Select
                      value={imageResolution}
                      label="图片分辨率"
                      onChange={(e) => onImageResolutionChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.image_resolution != null}
                    >
                      {IMAGE_RESOLUTION_OPTIONS.map((res) => (
                        <MenuItem key={res.value} value={res.value}>
                          {res.label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>图像模型</InputLabel>
                    <Select
                      value={imageModel}
                      label="图像模型"
                      onChange={(e) => onImageModelChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.image_model != null}
                    >
                      {IMAGE_MODEL_OPTIONS.map((model) => (
                        <MenuItem key={model.value} value={model.value}>
                          {model.label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControl fullWidth size="small">
                    <InputLabel>视频模型</InputLabel>
                    <Select
                      value={videoModel}
                      label="视频模型"
                      onChange={(e) => onVideoModelChange(e.target.value)}
                      disabled={isLocked && lockedConfig?.video_model != null}
                    >
                      {VIDEO_MODEL_OPTIONS.map((model) => (
                        <MenuItem key={model.value} value={model.value}>
                          {model.label}
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
              模型配置与联动
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
                    label="启用视觉理解审查"
                  />
                  {enableVisionReview && (
                    <FormControl fullWidth size="small" sx={{ mt: 1 }}>
                      <InputLabel>视觉理解模型</InputLabel>
                      <Select
                        value={visionModel}
                        label="视觉理解模型"
                        onChange={(e) => onVisionModelChange(e.target.value)}
                        disabled={isLocked && lockedConfig?.vision_model != null}
                      >
                        {VISION_MODEL_OPTIONS.map((model) => (
                          <MenuItem key={model.value} value={model.value}>
                            {model.label}
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
                    label="启用视频编辑"
                  />
                  {enableVideoEdit && (
                    <FormControl fullWidth size="small" sx={{ mt: 1 }}>
                      <InputLabel>视频编辑模型</InputLabel>
                      <Select
                        value={videoEditModel}
                        label="视频编辑模型"
                        onChange={(e) => onVideoEditModelChange(e.target.value)}
                        disabled={isLocked && lockedConfig?.video_edit_model != null}
                      >
                        {VIDEO_EDIT_MODEL_OPTIONS.map((model) => (
                          <MenuItem key={model.value} value={model.value}>
                            {model.label}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  )}
                </Grid>
                <Grid item xs={12}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                    视觉理解模型用于生成过程中自动评估图像/视频质量，视频编辑模型用于分镜素材的精剪和风格迁移。
                  </Typography>
                </Grid>
              </Grid>
            </Paper>
          </Box>

          <Box>
            <Typography variant="subtitle2" gutterBottom>
              高级选项
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
                    label="智能调优"
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
                    label="视频确认"
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
                    label="提示词审核"
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
                    label="允许QC失败"
                  />
                </Grid>
                <Grid item xs={12}>
                  <TextField
                    fullWidth
                    size="small"
                    label="AB测试变体"
                    value={abVariant}
                    onChange={(e) => onAbVariantChange(e.target.value)}
                    placeholder="留空表示不启用AB测试"
                  />
                </Grid>
              </Grid>
            </Paper>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button
          variant="contained"
          startIcon={<PlayArrowIcon />}
          onClick={handleRun}
          disabled={running || selectedChapterIds.length === 0}
        >
          {running ? '启动中...' : '开始生成'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
