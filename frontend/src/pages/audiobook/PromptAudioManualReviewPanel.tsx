import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
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
      setSavedMessage(t('audiobook.promptAudioManualReview.savedNotice'))
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.promptAudioManualReview.saveFailed')))
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
          ? t('audiobook.promptAudioManualReview.asrQueuedWithJob', { jobId })
          : t('audiobook.promptAudioManualReview.asrQueued'),
      )
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.promptAudioManualReview.asrQueueFailed')))
    } finally {
      setQueueingTranscript(false)
    }
  }

  if (promptAudioReviewModels.length === 0) {
    return (
      <Alert severity="info">
        {t('audiobook.promptAudioManualReview.noFeedback')}
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
          {t('audiobook.promptAudioManualReview.title')}
        </Typography>
        <TextField
          select
          size="small"
          label={t('audiobook.promptAudioManualReview.modelLabel')}
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
            label={`${t('audiobook.promptAudioManualReview.segmentList', {
              indices: currentModel.manualReviewSegmentIndices.map((item) => item + 1).join(', '),
            })}`}
          />
        )}
      </Stack>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
        <TextField
          select
          size="small"
          label={t('audiobook.promptAudioManualReview.tagParseLabel')}
          value={tagParseSuccess}
          onChange={(event) => setTagParseSuccess(event.target.value as ReviewBooleanValue)}
          sx={{ minWidth: { xs: '100%', sm: 130 } }}
        >
          <MenuItem value="unknown">{t('audiobook.promptAudioManualReview.unrated')}</MenuItem>
          <MenuItem value="true">{t('audiobook.promptAudioManualReview.passed')}</MenuItem>
          <MenuItem value="false">{t('audiobook.promptAudioManualReview.failed')}</MenuItem>
        </TextField>
        <TextField
          select
          size="small"
          label={t('audiobook.promptAudioManualReview.contaminationLabel')}
          value={textContamination}
          onChange={(event) => setTextContamination(event.target.value as ReviewBooleanValue)}
          sx={{ minWidth: { xs: '100%', sm: 130 } }}
        >
          <MenuItem value="unknown">{t('audiobook.promptAudioManualReview.unrated')}</MenuItem>
          <MenuItem value="false">{t('audiobook.promptAudioManualReview.noContamination')}</MenuItem>
          <MenuItem value="true">{t('audiobook.promptAudioManualReview.contaminated')}</MenuItem>
        </TextField>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minHeight: 40 }}>
          <Typography variant="caption" color="text.secondary">
            {t('audiobook.promptAudioManualReview.manualScoreLabel')}
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
        label={t('audiobook.promptAudioManualReview.asrTranscriptLabel')}
        value={asrTranscript}
        onChange={(event) => setAsrTranscript(event.target.value)}
      />

      {asrAssist?.available && (
        <Alert severity={asrAssist.detectedTagResidue ? 'warning' : 'success'}>
          {t('audiobook.promptAudioManualReview.asrAssistSummary', {
            similarity: asrAssist.similarityScore !== null
              ? (asrAssist.similarityScore * 100).toFixed(1)
              : t('audiobook.promptAudioManualReview.unknownValue'),
            wer: asrAssist.wordErrorRate !== null
              ? (asrAssist.wordErrorRate * 100).toFixed(1)
              : t('audiobook.promptAudioManualReview.unknownValue'),
          })}
          {asrAssist.suggestedTextContamination === true
            ? t('audiobook.promptAudioManualReview.suggestContamination')
            : t('audiobook.promptAudioManualReview.noTagResidue')}
          {asrAssist.suggestedTagParseSuccess === false
            ? t('audiobook.promptAudioManualReview.suggestRecheckParse')
            : ''}
          {asrAssist.matchedTags.length > 0
            ? t('audiobook.promptAudioManualReview.matchedTags', {
                tags: asrAssist.matchedTags.join(', '),
              })
            : ''}
        </Alert>
      )}

      <TextField
        size="small"
        fullWidth
        multiline
        minRows={1}
        maxRows={2}
        label={t('audiobook.promptAudioManualReview.notesLabel')}
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
      />

      {currentModel?.manualReviewFields.reviewedAt && (
        <Typography variant="caption" color="text.secondary">
          {t('audiobook.promptAudioManualReview.reviewedAtLabel', {
            datetime: currentModel.manualReviewFields.reviewedAt,
          })}
          {currentModel.manualReviewFields.reviewedBy !== null
            ? t('audiobook.promptAudioManualReview.reviewedBy', {
                user: currentModel.manualReviewFields.reviewedBy,
              })
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
          {queueingTranscript
            ? t('audiobook.promptAudioManualReview.queueingText')
            : t('audiobook.promptAudioManualReview.queueTranscript')}
        </Button>
        <Button
          size="small"
          variant="contained"
          startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
          disabled={!currentModel || submitting}
          onClick={handleSave}
          sx={audiobookButtonSx.brandContained}
        >
          {submitting
            ? t('audiobook.mimoVoiceAssetWorkbench.savingText')
            : t('audiobook.promptAudioManualReview.saveReview')}
        </Button>
        <Button size="small" variant="text" onClick={onCollapse}>
          {t('audiobook.mimoVoiceAssetWorkbench.collapse')}
        </Button>
      </Stack>
    </Box>
  )
}

export default PromptAudioManualReviewPanel
