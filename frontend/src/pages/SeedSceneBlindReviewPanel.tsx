import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, Chip, CircularProgress, Paper, Rating, Stack, TextField,
  ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material'
import SaveIcon from '@mui/icons-material/Save'

import {
  apiClient,
  extractApiErrorMessage,
  type SeedSceneBlindAudioResponse,
  type SeedSceneBlindBatchResponse,
  type SeedSceneBlindReviewRecord,
} from '@/services/api'

const REVIEW_ITEMS = [
  ['dialogueComplete', '台词完整'],
  ['plotUnderstandable', '剧情可懂'],
  ['voicesDistinct', '角色可区分'],
  ['voiceConsistent', '音色一致'],
  ['emotionNatural', '情绪自然'],
  ['effectsTimed', '音效时序'],
  ['musicAppropriate', '配乐合适'],
  ['mixClear', '混音清晰'],
  ['usable', '可以使用'],
] as const

type ReviewKey = typeof REVIEW_ITEMS[number][0]
type ReviewFlags = Record<ReviewKey, boolean | null>

const emptyFlags = (): ReviewFlags => Object.fromEntries(
  REVIEW_ITEMS.map(([key]) => [key, null]),
) as ReviewFlags

const audioDataUrl = (audio: SeedSceneBlindAudioResponse) =>
  `data:${audio.audio_mime_type};base64,${audio.audio_data_base64}`

interface SeedSceneBlindReviewPanelProps {
  batchId: string
}

const SeedSceneBlindReviewPanel = ({ batchId }: SeedSceneBlindReviewPanelProps) => {
  const [batch, setBatch] = useState<SeedSceneBlindBatchResponse | null>(null)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [audio, setAudio] = useState<SeedSceneBlindAudioResponse | null>(null)
  const [record, setRecord] = useState<SeedSceneBlindReviewRecord | null>(null)
  const [score, setScore] = useState<number | null>(null)
  const [flags, setFlags] = useState<ReviewFlags>(emptyFlags)
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedSample = batch?.samples[selectedIndex] ?? null
  const complete = score !== null && Object.values(flags).every((value) => value !== null)
  const locked = record?.locked === true
  useEffect(() => {
    let active = true
    setLoading(true)
    apiClient.getSeedSceneBlindReviewBatch(batchId)
      .then((response) => {
        if (active) setBatch(response.data)
      })
      .catch(async (requestError) => {
        if (active) setError(await extractApiErrorMessage(requestError, '加载盲评批次失败'))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [batchId])

  useEffect(() => {
    if (!selectedSample) return
    let active = true
    setAudio(null)
    setRecord(null)
    setScore(null)
    setFlags(emptyFlags())
    setNotes('')
    setError(null)
    setLoading(true)
    Promise.all([
      apiClient.getSeedSceneBlindReviewAudio(batchId, selectedSample.anonymous_id),
      apiClient.getMySeedSceneBlindReview(batchId, selectedSample.anonymous_id)
        .then((response) => response.data)
        .catch((requestError: { response?: { status?: number } }) => {
          if (requestError.response?.status === 404) return null
          throw requestError
        }),
    ])
      .then(([audioResponse, storedRecord]) => {
        if (!active) return
        setAudio(audioResponse.data)
        if (storedRecord) {
          setRecord(storedRecord)
          setScore(storedRecord.score)
          setFlags({ ...emptyFlags(), ...storedRecord.flags } as ReviewFlags)
          setNotes(storedRecord.notes)
        }
      })
      .catch(async (requestError) => {
        if (active) setError(await extractApiErrorMessage(requestError, '加载盲评样本失败'))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [batchId, selectedSample])

  const submit = async () => {
    if (!selectedSample || !complete || locked) return
    setSaving(true)
    setError(null)
    try {
      const response = await apiClient.submitSeedSceneBlindReview(
        batchId,
        selectedSample.anonymous_id,
        {
          score,
          flags: Object.fromEntries(
            Object.entries(flags).map(([key, value]) => [key, value === true]),
          ),
          notes: notes.trim(),
        },
      )
      setRecord(response.data)
    } catch (requestError) {
      setError(await extractApiErrorMessage(requestError, '提交盲评失败'))
    } finally {
      setSaving(false)
    }
  }

  if (loading && !batch) {
    return <Box sx={{ minHeight: 420, display: 'grid', placeItems: 'center' }}><CircularProgress /></Box>
  }
  if (!batch) return <Box sx={{ p: 3 }}><Alert severity="error">{error || '盲评批次不可用'}</Alert></Box>

  return (
    <Box sx={{ maxWidth: 920, mx: 'auto', p: { xs: 2, md: 3 } }}>
      <Stack spacing={2}>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Typography variant="h5" sx={{ fontWeight: 700 }}>场景盲评</Typography>
          <Stack direction="row" spacing={1}>
            <Chip size="small" label={`${selectedIndex + 1}/${batch.samples.length}`} />
            {locked && <Chip size="small" color="success" label="已提交" />}
          </Stack>
        </Stack>
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          {batch.samples.map((sample, index) => (
            <Button
              key={sample.anonymous_id}
              size="small"
              variant={index === selectedIndex ? 'contained' : 'outlined'}
              onClick={() => setSelectedIndex(index)}
            >
              {sample.blind_label}
            </Button>
          ))}
        </Stack>
        {error && <Alert severity="error">{error}</Alert>}
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 1 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>{selectedSample?.blind_label}</Typography>
          {loading || !audio
            ? <CircularProgress size={24} />
            : <Box component="audio" src={audioDataUrl(audio)} controls sx={{ width: '100%', display: 'block' }} />}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 1 }}>
          <Stack spacing={1.5}>
            <Stack direction="row" alignItems="center" spacing={2}>
              <Typography variant="body2" sx={{ width: 96 }}>综合评分</Typography>
              <Rating
                precision={0.5}
                value={score}
                disabled={locked}
                onChange={(_event, value) => setScore(value)}
              />
            </Stack>
            {REVIEW_ITEMS.map(([key, label]) => (
              <Stack key={key} direction="row" alignItems="center" justifyContent="space-between">
                <Typography variant="body2">{label}</Typography>
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  value={flags[key] === null ? '' : flags[key] ? 'pass' : 'fail'}
                  disabled={locked}
                  onChange={(_event, value) => {
                    if (!value) return
                    setFlags((current) => ({ ...current, [key]: value === 'pass' }))
                  }}
                >
                  <ToggleButton value="pass" color="success">通过</ToggleButton>
                  <ToggleButton value="fail" color="error">未通过</ToggleButton>
                </ToggleButtonGroup>
              </Stack>
            ))}
            <TextField
              label="评审备注"
              multiline
              minRows={3}
              value={notes}
              disabled={locked}
              onChange={(event) => setNotes(event.target.value)}
            />
            <Button
              variant="contained"
              startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <SaveIcon />}
              disabled={!complete || locked || saving || !audio}
              onClick={() => void submit()}
            >
              {locked ? '已锁定' : '提交评审'}
            </Button>
          </Stack>
        </Paper>
      </Stack>
    </Box>
  )
}

export default SeedSceneBlindReviewPanel
