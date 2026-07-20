import { useEffect, useMemo, useState } from 'react'

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Rating,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import SaveIcon from '@mui/icons-material/Save'
import SubtitlesIcon from '@mui/icons-material/Subtitles'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { audiobookButtonSx } from './audiobookTheme'
import { getPromptAudioQualitySummary } from './stageMetricsUtils'
import type { ChapterAudio } from './types'

type ReviewBooleanValue = 'unknown' | 'true' | 'false'

interface PromptAudioManualReviewPanelProps {
  chapterAudio: ChapterAudio
  onCollapse: () => void
}

const formatReviewBooleanValue = (value: boolean | null): ReviewBooleanValue => {
  if (value === true) return 'true'
  if (value === false) return 'false'
  return 'unknown'
}

const parseReviewBooleanValue = (value: ReviewBooleanValue): boolean | null => {
  if (value === 'true') return true
  if (value === 'false') return false
  return null
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const PromptAudioManualReviewPanel = ({
  chapterAudio,
  onCollapse,
}: PromptAudioManualReviewPanelProps) => {
  const [localPromptAudioQuality, setLocalPromptAudioQuality] = useState<Record<string, unknown> | null>(null)
  const [selectedModel, setSelectedModel] = useState('')
  const [tagParseSuccess, setTagParseSuccess] = useState<ReviewBooleanValue>('unknown')
  const [textContamination, setTextContamination] = useState<ReviewBooleanValue>('unknown')
  const [score, setScore] = useState<number | null>(null)
  const [notes, setNotes] = useState('')
  const [asrTranscript, setAsrTranscript] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [queueingTranscript, setQueueingTranscript] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedMessage, setSavedMessage] = useState<string | null>(null)

  const promptAudioQualitySummary = useMemo(
    () => getPromptAudioQualitySummary({
      prompt_audio_quality: localPromptAudioQuality ?? chapterAudio.prompt_audio_quality,
    }),
    [chapterAudio.prompt_audio_quality, localPromptAudioQuality],
  )
  const promptAudioReviewModels = promptAudioQualitySummary?.models ?? []
  const currentModel = useMemo(
    () => promptAudioReviewModels.find((model) => model.model === selectedModel) ?? null,
    [promptAudioReviewModels, selectedModel],
  )

  useEffect(() => {
    setLocalPromptAudioQuality(null)
  }, [chapterAudio.id])

  useEffect(() => {
    if (promptAudioReviewModels.length === 0) {
      if (selectedModel) setSelectedModel('')
      return
    }

    if (!promptAudioReviewModels.some((model) => model.model === selectedModel)) {
      setSelectedModel(promptAudioReviewModels[0].model)
    }
  }, [promptAudioReviewModels, selectedModel])

  useEffect(() => {
    if (!currentModel) return

    const fields = currentModel.manualReviewFields
    setTagParseSuccess(formatReviewBooleanValue(fields.tagParseSuccess))
    setTextContamination(formatReviewBooleanValue(fields.textContamination))
    setScore(fields.score)
    setNotes(fields.notes)
    setAsrTranscript(fields.asrTranscript)
    setError(null)
  }, [currentModel])

  const handleSave = async () => {
    if (!currentModel || submitting) return

    setSubmitting(true)
    setError(null)
    setSavedMessage(null)
    try {
      const response = await apiClient.updatePromptAudioManualReview(chapterAudio.id, {
        model: currentModel.model,
        tag_parse_success: parseReviewBooleanValue(tagParseSuccess),
        text_contamination: parseReviewBooleanValue(textContamination),
        score,
        notes: notes || null,
        asr_transcript: asrTranscript || null,
      })
      if (isRecord(response.data.prompt_audio_quality)) {
        setLocalPromptAudioQuality(response.data.prompt_audio_quality)
      }
      setSavedMessage('Prompt/Audio 验收已保存')
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '保存 Prompt/Audio 验收失败'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleQueueTranscript = async () => {
    if (queueingTranscript) return

    setQueueingTranscript(true)
    setError(null)
    setSavedMessage(null)
    try {
      const response = await apiClient.queuePromptAudioTranscript(chapterAudio.id, {
        model: currentModel?.model ?? null,
        provider: 'mimo',
        confirm_cost: true,
      })
      const jobId = response.data.job_id || response.data.task_id
      setSavedMessage(
        jobId
          ? `ASR 转写任务已进入队列：${jobId}`
          : 'ASR 转写任务已进入队列',
      )
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '排队 ASR 转写失败'))
    } finally {
      setQueueingTranscript(false)
    }
  }

  if (promptAudioReviewModels.length === 0) {
    return (
      <Alert severity="info">
        暂无 Prompt/Audio 质量回写
      </Alert>
    )
  }

  const asrAssist = currentModel?.manualReviewFields.asrAssist ?? null

  return (
    <Box
      sx={{
        mt: 1,
        p: 1,
        backgroundColor: 'action.hover',
        borderRadius: 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
      }}
    >
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'stretch', sm: 'center' }}>
        <Typography variant="caption" sx={{ fontWeight: 700, minWidth: 130 }}>
          Prompt/Audio 验收
        </Typography>
        <TextField
          select
          size="small"
          label="模型"
          value={selectedModel}
          onChange={(event) => {
            setSelectedModel(event.target.value)
            setSavedMessage(null)
          }}
          sx={{ minWidth: { xs: '100%', sm: 220 } }}
        >
          {promptAudioReviewModels.map((model) => (
            <MenuItem key={model.model} value={model.model}>
              {model.model}
            </MenuItem>
          ))}
        </TextField>
        {currentModel?.modelFamily && (
          <Chip size="small" label={currentModel.modelFamily} />
        )}
        {currentModel && currentModel.manualReviewSegmentIndices.length > 0 && (
          <Chip
            size="small"
            variant="outlined"
            label={`片段 ${currentModel.manualReviewSegmentIndices.map((item) => item + 1).join(', ')}`}
          />
        )}
      </Stack>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
        <TextField
          select
          size="small"
          label="标签解析"
          value={tagParseSuccess}
          onChange={(event) => setTagParseSuccess(event.target.value as ReviewBooleanValue)}
          sx={{ minWidth: { xs: '100%', sm: 130 } }}
        >
          <MenuItem value="unknown">未评</MenuItem>
          <MenuItem value="true">通过</MenuItem>
          <MenuItem value="false">失败</MenuItem>
        </TextField>
        <TextField
          select
          size="small"
          label="正文污染"
          value={textContamination}
          onChange={(event) => setTextContamination(event.target.value as ReviewBooleanValue)}
          sx={{ minWidth: { xs: '100%', sm: 130 } }}
        >
          <MenuItem value="unknown">未评</MenuItem>
          <MenuItem value="false">无污染</MenuItem>
          <MenuItem value="true">有污染</MenuItem>
        </TextField>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minHeight: 40 }}>
          <Typography variant="caption" color="text.secondary">
            人工评分
          </Typography>
          <Rating
            size="small"
            precision={0.5}
            value={score}
            onChange={(_, value) => setScore(value)}
          />
        </Box>
      </Stack>

      <TextField
        size="small"
        fullWidth
        multiline
        minRows={1}
        maxRows={2}
        label="ASR 转写文本"
        value={asrTranscript}
        onChange={(event) => setAsrTranscript(event.target.value)}
      />

      {asrAssist?.available && (
        <Alert severity={asrAssist.detectedTagResidue ? 'warning' : 'success'}>
          ASR 辅助：
          相似度 {asrAssist.similarityScore !== null ? (asrAssist.similarityScore * 100).toFixed(1) : '未知'}%，
          WER {asrAssist.wordErrorRate !== null ? (asrAssist.wordErrorRate * 100).toFixed(1) : '未知'}%。
          {asrAssist.suggestedTextContamination === true ? ' 建议标记正文污染。' : ' 未发现明显标签残留。'}
          {asrAssist.suggestedTagParseSuccess === false ? ' 建议复核标签解析失败。' : ''}
          {asrAssist.matchedTags.length > 0 ? ` 命中标签：${asrAssist.matchedTags.join(', ')}` : ''}
        </Alert>
      )}

      <TextField
        size="small"
        fullWidth
        multiline
        minRows={1}
        maxRows={2}
        label="备注"
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
      />

      {currentModel?.manualReviewFields.reviewedAt && (
        <Typography variant="caption" color="text.secondary">
          最近验收：{currentModel.manualReviewFields.reviewedAt}
          {currentModel.manualReviewFields.reviewedBy !== null
            ? ` · 用户 ${currentModel.manualReviewFields.reviewedBy}`
            : ''}
        </Typography>
      )}

      {error && <Alert severity="error">{error}</Alert>}
      {savedMessage && <Alert severity="success">{savedMessage}</Alert>}

      <Stack direction="row" spacing={1} justifyContent="flex-end">
        <Button
          size="small"
          variant="outlined"
          startIcon={queueingTranscript ? <CircularProgress size={16} color="inherit" /> : <SubtitlesIcon />}
          disabled={queueingTranscript}
          onClick={handleQueueTranscript}
          sx={audiobookButtonSx.brandOutlined}
        >
          {queueingTranscript ? '排队中...' : '排队转写'}
        </Button>
        <Button
          size="small"
          variant="contained"
          startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
          disabled={!currentModel || submitting}
          onClick={handleSave}
          sx={audiobookButtonSx.brandContained}
        >
          {submitting ? '保存中...' : '保存验收'}
        </Button>
        <Button size="small" variant="text" onClick={onCollapse}>
          收起
        </Button>
      </Stack>
    </Box>
  )
}

export default PromptAudioManualReviewPanel
