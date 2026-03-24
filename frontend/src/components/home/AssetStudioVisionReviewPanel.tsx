import { useEffect, useState } from 'react'
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
  Stack,
  TextField,
  Typography,
} from '@mui/material'

import {
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'

import type {
  AssetStudioVisionCriterionScore,
  AssetStudioVisionReviewResponse,
} from '@/services/api'

const VISION_REVIEW_MODEL_ID = 'qwen3-vl-plus'

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
        上传待识别素材
      </Typography>
      <Typography sx={{ color: 'rgba(255,255,255,0.62)', fontSize: '0.82rem', mt: 0.6, maxWidth: 360 }}>
        支持图片或视频。系统会根据素材类型自动切换到图像识别或视频检查链路。
      </Typography>
      <Chip
        size="small"
        label={file ? file.name : '点击上传图片 / 视频'}
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
  return (
    <Box
      sx={{
        borderRadius: 3,
        p: 2,
        minHeight: 240,
        border: '1px solid rgba(255,255,255,0.1)',
        backgroundColor: 'rgba(255,255,255,0.04)',
      }}
    >
      <Typography sx={{ color: 'white', fontSize: '0.92rem', fontWeight: 700, mb: 1.2 }}>
        素材预览
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
                alt={file?.name || 'vision review preview'}
                sx={{ width: '100%', display: 'block', maxHeight: 340, objectFit: 'contain', backgroundColor: 'black' }}
              />
            )}
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip
              size="small"
              icon={assetType === 'video' ? <MovieFilterOutlinedIcon /> : <VisibilityOutlinedIcon />}
              label={assetType === 'video' ? '视频识别' : '图片识别'}
              variant="outlined"
              sx={{ color: 'white' }}
            />
            {file ? (
              <Chip size="small" label={file.name} variant="outlined" sx={{ color: 'white', maxWidth: '100%' }} />
            ) : null}
          </Stack>
        </Stack>
      ) : (
        <Stack spacing={1} justifyContent="center" sx={{ minHeight: 180 }}>
          <Typography sx={{ color: 'rgba(255,255,255,0.54)', fontSize: '0.9rem', lineHeight: 1.8 }}>
            这里会展示待识别素材的本地预览，方便在拿到评价时快速对照问题位置。
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
    <Box
      sx={{
        borderRadius: 2.5,
        p: 1.5,
        border: '1px solid rgba(255,255,255,0.08)',
        backgroundColor: 'rgba(255,255,255,0.03)',
      }}
    >
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
  const scoreTone = getScoreTone(result?.overall_score)
  const canReuseImageAsReference = Boolean(
    result?.asset_type === 'image' && sourceAssetType === 'image' && sourceAssetFile
  )

  return (
    <Box
      sx={{
        borderRadius: 3,
        p: 2,
        minHeight: 340,
        border: '1px solid rgba(255,255,255,0.1)',
        backgroundColor: 'rgba(255,255,255,0.04)',
      }}
    >
      <Typography sx={{ color: 'white', fontSize: '0.92rem', fontWeight: 700, mb: 1.2 }}>
        识别结果
      </Typography>

      {loading ? (
        <Stack spacing={1.2} alignItems="center" justifyContent="center" sx={{ minHeight: 260 }}>
          <CircularProgress size={28} sx={{ color: '#f1b74a' }} />
          <Typography sx={{ color: 'rgba(255,255,255,0.74)', fontSize: '0.9rem' }}>
            正在调用视觉模型进行识别与评价...
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
              label={result.asset_type === 'video' ? '视频素材' : '图片素材'}
              variant="outlined"
              sx={{ color: 'white' }}
            />
            <Chip size="small" label={result.model_id} variant="outlined" sx={{ color: 'white' }} />
            <Chip
              size="small"
              label={
                typeof result.overall_score === 'number'
                  ? `综合评分 ${result.overall_score.toFixed(1)} / 10`
                  : '综合评分待补充'
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
            title="优点"
            items={result.strengths}
            emptyText="模型未返回明显优势项，可以直接参考下方问题和改词建议继续优化。"
            icon={<VisibilityOutlinedIcon fontSize="small" />}
          />
          <SectionList
            title="问题"
            items={result.issues}
            emptyText="当前没有识别到显著问题，但仍建议结合综合评分再做一轮微调。"
            icon={<AutoFixHighOutlinedIcon fontSize="small" />}
          />
          <SectionList
            title="改词建议"
            items={result.prompt_suggestions}
            emptyText="模型未返回明确改词建议，系统已经在末尾自动整理了修改后的提示词。"
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
                修改后的提示词
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<ContentCopyOutlinedIcon />}
                  onClick={() => onCopyPrompt(result.revised_prompt)}
                  sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.2)' }}
                >
                  {copyFeedback || '复制提示词'}
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
                  sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.2)' }}
                >
                  仅带提示词到图片生成
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
                  sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.2)' }}
                >
                  仅带提示词到视频生成
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
                    sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.2)' }}
                  >
                    带入参考生图
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
                    sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.2)' }}
                  >
                    带入图生视频
                  </Button>
                ) : null}
              </Stack>
            </Stack>
            {result.asset_type === 'video' ? (
              <Typography sx={{ mb: 1, color: 'rgba(255,255,255,0.58)', fontSize: '0.8rem', lineHeight: 1.7 }}>
                当前工作台暂无视频参考生成入口，所以视频识别结果只能复用修改后的提示词，不能直接把视频素材带入生成链路。
              </Typography>
            ) : null}
            <TextField
              fullWidth
              multiline
              minRows={5}
              value={result.revised_prompt}
              InputProps={{ readOnly: true }}
              sx={{
                '& .MuiOutlinedInput-root': {
                  color: 'white',
                  backgroundColor: 'rgba(8,11,14,0.45)',
                },
              }}
            />
          </Box>
        </Stack>
      ) : (
        <Stack spacing={1} justifyContent="center" sx={{ minHeight: 260 }}>
          <Typography sx={{ color: 'rgba(255,255,255,0.52)', fontSize: '0.9rem', lineHeight: 1.8 }}>
            上传图片或视频后，这里会返回视觉模型给出的评价、问题清单、改词建议，以及可直接继续生成的修改后提示词。
          </Typography>
        </Stack>
      )}
    </Box>
  )
}

export default function AssetStudioVisionReviewPanel({
  onUseResult,
}: AssetStudioVisionReviewPanelProps) {
  const [assetFile, setAssetFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [originalPrompt, setOriginalPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AssetStudioVisionReviewResponse | null>(null)
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null)

  const assetType = resolvePreviewAssetType(assetFile)

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
      setCopyFeedback('已复制')
      window.setTimeout(() => setCopyFeedback(null), 1800)
    } catch {
      setCopyFeedback('复制失败')
      window.setTimeout(() => setCopyFeedback(null), 1800)
    }
  }

  const handleReview = async () => {
    if (!assetFile) {
      setError('请先上传需要识别的图片或视频。')
      return
    }

    setLoading(true)
    setError(null)
    setCopyFeedback(null)
    try {
      const formData = new FormData()
      formData.append('asset_file', assetFile)
      formData.append('model_id', VISION_REVIEW_MODEL_ID)
      if (originalPrompt.trim()) {
        formData.append('original_prompt', originalPrompt.trim())
      }

      const response = await apiClient.reviewAssetStudioVision(formData)
      setResult(response.data as AssetStudioVisionReviewResponse)
    } catch (requestError) {
      setError(await extractApiErrorMessage(requestError, '视觉识别失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', xl: '1.02fr 0.98fr' } }}>
        <Stack spacing={2}>
          <Box
            sx={{
              p: 2,
              borderRadius: 3,
              border: '1px solid rgba(255,255,255,0.1)',
              backgroundColor: 'rgba(255,255,255,0.03)',
            }}
          >
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" label={`当前模型：${VISION_REVIEW_MODEL_ID}`} sx={{ color: 'white' }} variant="outlined" />
              <Chip size="small" label="图片识别 / 视频检查" sx={{ color: 'white' }} variant="outlined" />
              <Chip size="small" label="仅分析不生成" sx={{ color: 'white' }} variant="outlined" />
              <Chip size="small" label="评价 + 改词 + 修改后提示词" sx={{ color: 'white' }} variant="outlined" />
            </Stack>
            <Typography sx={{ mt: 1.25, color: 'rgba(255,255,255,0.68)', fontSize: '0.84rem', lineHeight: 1.8 }}>
              根据模型中心当前能力，这个入口固定使用具备图像理解与视频理解能力的
              {' '}
              {VISION_REVIEW_MODEL_ID}
              {' '}
              ，避免出现“可见但不可用”的模型选项。
            </Typography>
          </Box>

          <UploadPanel file={assetFile} onChange={handleFileChange} />

          <TextField
            multiline
            minRows={6}
            label="原始提示词（可选）"
            value={originalPrompt}
            onChange={(event) => setOriginalPrompt(event.target.value)}
            placeholder="如果这张图或这段视频是根据某个提示词生成的，可以贴在这里。识别结果会在末尾给出更贴近原意的修改后提示词。"
            InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
            sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
          />

          <Alert severity="info" sx={{ borderRadius: 2.5 }}>
            不填原始提示词也能识别，但填写后，系统整理出的“修改后的提示词”会更适合直接重新生成。
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
        <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.84rem', lineHeight: 1.7 }}>
          识别结果会优先展示综合评价，并在最下方附带可继续调用生成接口的修改后提示词。
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
          {loading ? '识别中...' : '开始识别'}
        </Button>
      </Stack>
    </Box>
  )
}
