import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import AddPhotoAlternateOutlinedIcon from '@mui/icons-material/AddPhotoAlternateOutlined'
import AutoFixHighOutlinedIcon from '@mui/icons-material/AutoFixHighOutlined'
import ContentCopyOutlinedIcon from '@mui/icons-material/ContentCopyOutlined'
import MovieFilterOutlinedIcon from '@mui/icons-material/MovieFilterOutlined'
import TipsAndUpdatesOutlinedIcon from '@mui/icons-material/TipsAndUpdatesOutlined'
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  MenuItem,
  Stack,
  Typography,
} from '@mui/material'

import {
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'

import type {
  AssetStudioModelCatalogOption,
  AssetStudioVisionCriterionScore,
  AssetStudioVisionReviewResponse,
} from '@/services/api'
import { useAssetStudioModelCatalog } from '@/hooks/useAssetStudioModelCatalog'
import { useTranslation } from 'react-i18next'

import {
  FormHelperText,
  InputLabel,
  Select,
  TextField,
  WORKBENCH_COMPACT_CARD_SX,
  WORKBENCH_FIELD_COLORS,
  WORKBENCH_HINT_SX,
  WORKBENCH_INNER_CARD_SX,
  WORKBENCH_NEUTRAL_CHIP_SX,
  WORKBENCH_SUBTLE_ACTION_BUTTON_SX,
} from './assetStudioFieldStyles'

interface VisionModelOption {
  value: string
  label: string
  helper: string
}

function mapCatalogOptionToVisionModelOption(option: AssetStudioModelCatalogOption): VisionModelOption {
  return { value: option.model_id, label: option.label, helper: option.helper }
}

// Select 默认整块回显选中 MenuItem 的 children，这里每项是"名称+定位说明"两行，
// 关闭态会把说明一并带进来并撑高控件，所以只回显模型名。
function resolveVisionModelLabel(options: VisionModelOption[], value: unknown): ReactNode {
  const modelId = String(value ?? '')
  return options.find((option) => option.value === modelId)?.label ?? modelId
}

export interface AssetStudioVisionReusePayload {
  target: 'image' | 'video'
  prompt: string
  mode: 'prompt' | 'reference'
  referenceFile?: File | null
}

interface AssetStudioVisionReviewPanelProps {
  onUseResult?: (payload: AssetStudioVisionReusePayload) => void
}

function resolvePreviewAssetType(file: File | null): 'image' | 'video' | null {
  if (!file) {
    return null
  }
  const mime = (file.type || '').toLowerCase()
  if (mime.startsWith('image/')) {
    return 'image'
  }
  if (mime.startsWith('video/')) {
    return 'video'
  }
  const name = file.name.toLowerCase()
  if (/\.(png|jpg|jpeg|webp|bmp|gif)$/.test(name)) {
    return 'image'
  }
  if (/\.(mp4|mov|avi|mkv|webm|m4v)$/.test(name)) {
    return 'video'
  }
  return null
}

function getScoreTone(score?: number | null): {
  color: string
  backgroundColor: string
  borderColor: string
} {
  if (typeof score !== 'number') {
    return {
      color: 'rgba(255,255,255,0.82)',
      backgroundColor: 'rgba(255,255,255,0.08)',
      borderColor: 'rgba(255,255,255,0.12)',
    }
  }
  if (score >= 8) {
    return {
      color: '#9cff7a',
      backgroundColor: 'rgba(118,255,84,0.14)',
      borderColor: 'rgba(118,255,84,0.32)',
    }
  }
  if (score >= 6) {
    return {
      color: '#ffd36c',
      backgroundColor: 'rgba(255,211,108,0.14)',
      borderColor: 'rgba(255,211,108,0.32)',
    }
  }
  return {
    color: '#ff9b7c',
    backgroundColor: 'rgba(255,123,84,0.14)',
    borderColor: 'rgba(255,123,84,0.3)',
  }
}

function UploadPanel({
  file,
  onChange,
}: {
  file: File | null
  onChange: (file: File | null) => void
}) {
  const { t } = useTranslation()
  return (
    <Box
      component="label"
      sx={{
        minHeight: 154,
        borderRadius: 3,
        border: '1px dashed rgba(255,255,255,0.18)',
        backgroundColor: 'rgba(255,255,255,0.05)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 2,
        textAlign: 'center',
        cursor: 'pointer',
        transition: 'all 0.24s ease',
        '&:hover': {
          borderColor: 'rgba(241,183,74,0.52)',
          backgroundColor: 'rgba(255,255,255,0.08)',
        },
      }}
    >
      <AddPhotoAlternateOutlinedIcon sx={{ color: 'rgba(255,255,255,0.82)', fontSize: 28, mb: 1 }} />
      <Typography sx={{ color: 'white', fontSize: '0.95rem', fontWeight: 700 }}>
        {t('assetStudio.vision.upload.title')}
      </Typography>
      <Typography sx={{ color: 'rgba(255,255,255,0.62)', fontSize: '0.82rem', mt: 0.6, maxWidth: 360 }}>
        {t('assetStudio.vision.upload.hint')}
      </Typography>
      <Chip
        size="small"
        label={file ? file.name : t('assetStudio.vision.upload.clickLabel')}
        sx={{
          mt: 1.35,
          color: 'white',
          borderColor: file ? 'rgba(241,183,74,0.42)' : 'rgba(255,255,255,0.18)',
          backgroundColor: file ? 'rgba(241,183,74,0.16)' : 'rgba(255,255,255,0.08)',
          maxWidth: '100%',
        }}
        variant="outlined"
      />
      <input
        hidden
        type="file"
        accept="image/*,video/*"
        onChange={(event) => onChange(event.target.files?.[0] || null)}
      />
    </Box>
  )
}

function PreviewCard({
  file,
  previewUrl,
  assetType,
}: {
  file: File | null
  previewUrl: string | null
  assetType: 'image' | 'video' | null
}) {
  const { t } = useTranslation()
  return (
    <Box sx={{ ...WORKBENCH_INNER_CARD_SX, minHeight: 240 }}>
      <Typography sx={{ color: 'white', fontSize: '0.92rem', fontWeight: 700, mb: 1.2 }}>
        {t('assetStudio.vision.preview.title')}
      </Typography>

      {previewUrl && assetType ? (
        <Stack spacing={1.2}>
          <Box
            sx={{
              borderRadius: 2.5,
              overflow: 'hidden',
              backgroundColor: '#101317',
              border: '1px solid rgba(255,255,255,0.08)',
            }}
          >
            {assetType === 'video' ? (
              <Box
                component="video"
                src={previewUrl}
                controls
                sx={{ width: '100%', display: 'block', maxHeight: 340, backgroundColor: 'black' }}
              />
            ) : (
              <Box
                component="img"
                src={previewUrl}
                alt={file?.name || t('assetStudio.vision.preview.alt')}
                sx={{ width: '100%', display: 'block', maxHeight: 340, objectFit: 'contain', backgroundColor: 'black' }}
              />
            )}
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip
              size="small"
              icon={assetType === 'video' ? <MovieFilterOutlinedIcon /> : <VisibilityOutlinedIcon />}
              label={assetType === 'video' ? t('assetStudio.vision.preview.videoBadge') : t('assetStudio.vision.preview.imageBadge')}
              variant="outlined"
              sx={WORKBENCH_NEUTRAL_CHIP_SX}
            />
            {file ? (
              <Chip size="small" label={file.name} variant="outlined" sx={{ ...WORKBENCH_NEUTRAL_CHIP_SX, maxWidth: '100%' }} />
            ) : null}
          </Stack>
        </Stack>
      ) : (
        <Stack spacing={1} justifyContent="center" sx={{ minHeight: 180 }}>
          <Typography sx={{ color: 'rgba(255,255,255,0.54)', fontSize: '0.9rem', lineHeight: 1.8 }}>
            {t('assetStudio.vision.preview.emptyHint')}
          </Typography>
        </Stack>
      )}
    </Box>
  )
}

function CriterionCard({ item }: { item: AssetStudioVisionCriterionScore }) {
  const tone = getScoreTone(item.score)

  return (
    <Box
      sx={{
        borderRadius: 2.5,
        px: 1.4,
        py: 1.2,
        border: `1px solid ${tone.borderColor}`,
        backgroundColor: tone.backgroundColor,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
        <Typography sx={{ color: 'white', fontSize: '0.88rem', fontWeight: 700 }}>
          {item.label}
        </Typography>
        <Typography sx={{ color: tone.color, fontSize: '0.92rem', fontWeight: 800 }}>
          {typeof item.score === 'number' ? `${item.score.toFixed(1)} / 10` : '--'}
        </Typography>
      </Stack>
      {item.comment ? (
        <Typography sx={{ mt: 0.75, color: 'rgba(255,255,255,0.66)', fontSize: '0.8rem', lineHeight: 1.6 }}>
          {item.comment}
        </Typography>
      ) : null}
    </Box>
  )
}

function SectionList({
  title,
  items,
  emptyText,
  icon,
}: {
  title: string
  items: string[]
  emptyText: string
  icon: ReactNode
}) {
  return (
    <Box sx={WORKBENCH_COMPACT_CARD_SX}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', color: 'rgba(255,255,255,0.82)' }}>
          {icon}
        </Box>
        <Typography sx={{ color: 'white', fontSize: '0.9rem', fontWeight: 700 }}>{title}</Typography>
      </Stack>

      {items.length > 0 ? (
        <Stack spacing={0.85}>
          {items.map((item) => (
            <Typography
              key={`${title}-${item}`}
              sx={{ color: 'rgba(255,255,255,0.74)', fontSize: '0.84rem', lineHeight: 1.75 }}
            >
              • {item}
            </Typography>
          ))}
        </Stack>
      ) : (
        <Typography sx={{ color: 'rgba(255,255,255,0.52)', fontSize: '0.84rem', lineHeight: 1.7 }}>
          {emptyText}
        </Typography>
      )}
    </Box>
  )
}

function ResultPanel({
  loading,
  error,
  result,
  copyFeedback,
  onCopyPrompt,
  onUseResult,
  sourceAssetFile,
  sourceAssetType,
}: {
  loading: boolean
  error: string | null
  result: AssetStudioVisionReviewResponse | null
  copyFeedback: string | null
  onCopyPrompt: (prompt: string) => void
  onUseResult?: (payload: AssetStudioVisionReusePayload) => void
  sourceAssetFile: File | null
  sourceAssetType: 'image' | 'video' | null
}) {
  const { t } = useTranslation()
  const scoreTone = getScoreTone(result?.overall_score)
  const canReuseImageAsReference = Boolean(
    result?.asset_type === 'image' && sourceAssetType === 'image' && sourceAssetFile
  )

  return (
    <Box sx={{ ...WORKBENCH_INNER_CARD_SX, minHeight: 340 }}>
      <Typography sx={{ color: 'white', fontSize: '0.92rem', fontWeight: 700, mb: 1.2 }}>
        {t('assetStudio.vision.result.title')}
      </Typography>

      {loading ? (
        <Stack spacing={1.2} alignItems="center" justifyContent="center" sx={{ minHeight: 260 }}>
          <CircularProgress size={28} sx={{ color: '#f1b74a' }} />
          <Typography sx={{ color: 'rgba(255,255,255,0.74)', fontSize: '0.9rem' }}>
            {t('assetStudio.vision.result.loading')}
          </Typography>
        </Stack>
      ) : error ? (
        <Alert severity="error" sx={{ borderRadius: 2 }}>
          {error}
        </Alert>
      ) : result ? (
        <Stack spacing={1.5}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap" useFlexGap>
            <Chip
              size="small"
              label={result.asset_type === 'video' ? t('assetStudio.vision.result.videoAsset') : t('assetStudio.vision.result.imageAsset')}
              variant="outlined"
              sx={WORKBENCH_NEUTRAL_CHIP_SX}
            />
            <Chip size="small" label={result.model_id} variant="outlined" sx={WORKBENCH_NEUTRAL_CHIP_SX} />
            <Chip
              size="small"
              label={
                typeof result.overall_score === 'number'
                  ? t('assetStudio.vision.result.scoreValue', { score: result.overall_score.toFixed(1) })
                  : t('assetStudio.vision.result.scorePending')
              }
              sx={{
                color: scoreTone.color,
                backgroundColor: scoreTone.backgroundColor,
                border: `1px solid ${scoreTone.borderColor}`,
              }}
            />
          </Stack>

          <Alert
            severity={
              typeof result.overall_score === 'number'
                ? result.overall_score >= 8
                  ? 'success'
                  : result.overall_score >= 6
                    ? 'info'
                    : 'warning'
                : 'info'
            }
            sx={{ borderRadius: 2 }}
          >
            {result.summary}
          </Alert>

          {result.criteria_scores.length > 0 ? (
            <Box
              sx={{
                display: 'grid',
                gap: 1,
                gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' },
              }}
            >
              {result.criteria_scores.map((item) => (
                <CriterionCard key={item.name} item={item} />
              ))}
            </Box>
          ) : null}

          <SectionList
            title={t('assetStudio.vision.result.strengthsTitle')}
            items={result.strengths}
            emptyText={t('assetStudio.vision.result.strengthsEmpty')}
            icon={<VisibilityOutlinedIcon fontSize="small" />}
          />
          <SectionList
            title={t('assetStudio.vision.result.issuesTitle')}
            items={result.issues}
            emptyText={t('assetStudio.vision.result.issuesEmpty')}
            icon={<AutoFixHighOutlinedIcon fontSize="small" />}
          />
          <SectionList
            title={t('assetStudio.vision.result.suggestionsTitle')}
            items={result.prompt_suggestions}
            emptyText={t('assetStudio.vision.result.suggestionsEmpty')}
            icon={<TipsAndUpdatesOutlinedIcon fontSize="small" />}
          />

          <Box
            sx={{
              borderRadius: 2.5,
              p: 1.5,
              border: '1px solid rgba(241,183,74,0.26)',
              backgroundColor: 'rgba(241,183,74,0.08)',
            }}
          >
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              justifyContent="space-between"
              alignItems={{ xs: 'stretch', sm: 'center' }}
              spacing={1}
              sx={{ mb: 1 }}
            >
              <Typography sx={{ color: 'white', fontSize: '0.9rem', fontWeight: 700 }}>
                {t('assetStudio.vision.result.revisedPromptTitle')}
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<ContentCopyOutlinedIcon />}
                  onClick={() => onCopyPrompt(result.revised_prompt)}
                  sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                >
                  {copyFeedback || t('assetStudio.vision.result.copyPrompt')}
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() =>
                    onUseResult?.({
                      target: 'image',
                      prompt: result.revised_prompt,
                      mode: 'prompt',
                    })
                  }
                  disabled={!onUseResult}
                  sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                >
                  {t('assetStudio.vision.result.useImagePrompt')}
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() =>
                    onUseResult?.({
                      target: 'video',
                      prompt: result.revised_prompt,
                      mode: 'prompt',
                    })
                  }
                  disabled={!onUseResult}
                  sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                >
                  {t('assetStudio.vision.result.useVideoPrompt')}
                </Button>
                {canReuseImageAsReference ? (
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() =>
                      onUseResult?.({
                        target: 'image',
                        prompt: result.revised_prompt,
                        mode: 'reference',
                        referenceFile: sourceAssetFile,
                      })
                    }
                    disabled={!onUseResult}
                    sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                  >
                    {t('assetStudio.vision.result.referenceImage')}
                  </Button>
                ) : null}
                {canReuseImageAsReference ? (
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() =>
                      onUseResult?.({
                        target: 'video',
                        prompt: result.revised_prompt,
                        mode: 'reference',
                        referenceFile: sourceAssetFile,
                      })
                    }
                    disabled={!onUseResult}
                    sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                  >
                    {t('assetStudio.vision.result.referenceVideo')}
                  </Button>
                ) : null}
              </Stack>
            </Stack>
            {result.asset_type === 'video' ? (
              <Typography sx={{ ...WORKBENCH_HINT_SX, mb: 1 }}>
                {t('assetStudio.vision.result.videoNoReferenceHint')}
              </Typography>
            ) : null}
            <TextField
              fullWidth
              multiline
              minRows={5}
              value={result.revised_prompt}
              InputProps={{ readOnly: true }}
            />
          </Box>
        </Stack>
      ) : (
        <Stack spacing={1} justifyContent="center" sx={{ minHeight: 260 }}>
          <Typography sx={{ color: 'rgba(255,255,255,0.52)', fontSize: '0.9rem', lineHeight: 1.8 }}>
            {t('assetStudio.vision.result.emptyHint')}
          </Typography>
        </Stack>
      )}
    </Box>
  )
}

export default function AssetStudioVisionReviewPanel({
  onUseResult,
}: AssetStudioVisionReviewPanelProps) {
  const { t } = useTranslation()
  const { catalog, loading: catalogLoading, error: catalogError } = useAssetStudioModelCatalog()
  const [assetFile, setAssetFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [originalPrompt, setOriginalPrompt] = useState('')
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AssetStudioVisionReviewResponse | null>(null)
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null)

  const assetType = resolvePreviewAssetType(assetFile)
  // 档位名单与默认值都来自后端统一模型清单，页面不再自持档位表
  const visionModelOptions = useMemo(
    () => catalog?.groups.vision_review?.map(mapCatalogOptionToVisionModelOption) ?? [],
    [catalog],
  )
  const visionModelId = selectedModel
    || catalog?.defaults.asset_studio_vision_review
    || visionModelOptions[0]?.value
    || ''

  useEffect(() => {
    if (!assetFile) {
      setPreviewUrl(null)
      return
    }

    const objectUrl = URL.createObjectURL(assetFile)
    setPreviewUrl(objectUrl)
    return () => {
      URL.revokeObjectURL(objectUrl)
    }
  }, [assetFile])

  const handleFileChange = (nextFile: File | null) => {
    setAssetFile(nextFile)
    setError(null)
    setResult(null)
    setCopyFeedback(null)
  }

  const handleCopyPrompt = async (prompt: string) => {
    if (!prompt.trim()) {
      return
    }
    try {
      await navigator.clipboard.writeText(prompt)
      setCopyFeedback(t('assetStudio.vision.result.copyDone'))
      window.setTimeout(() => setCopyFeedback(null), 1800)
    } catch {
      setCopyFeedback(t('assetStudio.vision.result.copyFailed'))
      window.setTimeout(() => setCopyFeedback(null), 1800)
    }
  }

  const handleReview = async () => {
    if (!assetFile) {
      setError(t('assetStudio.vision.panel.uploadFirstError'))
      return
    }

    setLoading(true)
    setError(null)
    setCopyFeedback(null)
    try {
      const formData = new FormData()
      formData.append('asset_file', assetFile)
      if (visionModelId) {
        formData.append('model_id', visionModelId)
      }
      if (originalPrompt.trim()) {
        formData.append('original_prompt', originalPrompt.trim())
      }

      const response = await apiClient.reviewAssetStudioVision(formData)
      setResult(response.data as AssetStudioVisionReviewResponse)
    } catch (requestError) {
      setError(await extractApiErrorMessage(requestError, t('assetStudio.vision.panel.reviewFailed')))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', xl: '1.02fr 0.98fr' } }}>
        <Stack spacing={2}>
          <Box sx={WORKBENCH_INNER_CARD_SX}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" label={t('assetStudio.vision.panel.badgeType')} sx={WORKBENCH_NEUTRAL_CHIP_SX} variant="outlined" />
              <Chip size="small" label={t('assetStudio.vision.panel.badgeAnalyze')} sx={WORKBENCH_NEUTRAL_CHIP_SX} variant="outlined" />
              <Chip size="small" label={t('assetStudio.vision.panel.badgeOutput')} sx={WORKBENCH_NEUTRAL_CHIP_SX} variant="outlined" />
            </Stack>
            <Typography sx={{ mt: 1.25, color: 'rgba(255,255,255,0.68)', fontSize: '0.84rem', lineHeight: 1.8 }}>
              {t('assetStudio.vision.panel.modelHint')}
            </Typography>
            
            <FormControl fullWidth size="small" variant="outlined" sx={{ mt: 1.5 }}>
              <InputLabel id="vision-model-select-label">
                {t('assetStudio.vision.panel.modelLabel')}
              </InputLabel>
              <Select
                labelId="vision-model-select-label"
                value={visionModelId}
                label={t('assetStudio.vision.panel.modelLabel')}
                disabled={catalogLoading || visionModelOptions.length === 0}
                onChange={(event) => setSelectedModel(event.target.value)}
                renderValue={(value) => resolveVisionModelLabel(visionModelOptions, value)}
              >
                {visionModelOptions.map((model) => (
                  <MenuItem key={model.value} value={model.value}>
                    <Stack spacing={0.5}>
                      <Typography sx={{ fontSize: '0.95rem', fontWeight: 600 }}>
                        {model.label}
                      </Typography>
                      <Typography sx={{ fontSize: '0.8rem', color: WORKBENCH_FIELD_COLORS.helper, lineHeight: 1.4 }}>
                        {model.helper}
                      </Typography>
                    </Stack>
                  </MenuItem>
                ))}
              </Select>
              {catalogError && !catalogLoading && (
                <FormHelperText error>{catalogError}</FormHelperText>
              )}
            </FormControl>
          </Box>

          <UploadPanel file={assetFile} onChange={handleFileChange} />

          <TextField
            multiline
            minRows={6}
            label={t('assetStudio.vision.panel.originalPromptLabel')}
            value={originalPrompt}
            onChange={(event) => setOriginalPrompt(event.target.value)}
            placeholder={t('assetStudio.vision.panel.originalPromptPlaceholder')}
          />

          <Alert severity="info" sx={{ borderRadius: 2.5 }}>
            {t('assetStudio.vision.panel.originalPromptHint')}
          </Alert>
        </Stack>

        <Stack spacing={2}>
          <PreviewCard file={assetFile} previewUrl={previewUrl} assetType={assetType} />
          <ResultPanel
            loading={loading}
            error={error}
            result={result}
            copyFeedback={copyFeedback}
            onCopyPrompt={handleCopyPrompt}
            onUseResult={onUseResult}
            sourceAssetFile={assetFile}
            sourceAssetType={assetType}
          />
        </Stack>
      </Box>

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        justifyContent="space-between"
        alignItems={{ xs: 'stretch', md: 'center' }}
        spacing={1.5}
        sx={{ mt: 2 }}
      >
        <Typography sx={WORKBENCH_HINT_SX}>
          {t('assetStudio.vision.panel.footerHint')}
        </Typography>
        <Button
          variant="contained"
          onClick={handleReview}
          disabled={loading || !assetFile}
          sx={{
            minWidth: 180,
            minHeight: 56,
            borderRadius: 3,
            background: 'linear-gradient(135deg, #cf9a24 0%, #f4c760 100%)',
            color: '#151004',
            fontWeight: 800,
            fontSize: '1.02rem',
            boxShadow: '0 18px 36px rgba(241,183,74,0.22)',
            '&:hover': {
              background: 'linear-gradient(135deg, #cf9a24 0%, #f4c760 100%)',
              filter: 'brightness(0.98)',
            },
          }}
        >
          {loading ? t('assetStudio.vision.panel.reviewing') : t('assetStudio.vision.panel.review')}
        </Button>
      </Stack>
    </Box>
  )
}
