import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Rating,
  Select,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import DownloadIcon from '@mui/icons-material/Download'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'
import SaveIcon from '@mui/icons-material/Save'

import {
  apiClient,
  extractApiErrorMessage,
  type SeedSceneTestCase,
  type SeedSceneTestPreviewResponse,
  type SeedSceneTestReferencePayload,
  type SeedSceneTestReferenceSlot,
} from '@/services/api'
import {
  buildSeedSceneTestReviewId,
  buildSeedSceneTestReviewExport,
  readSeedSceneTestReviews,
  summarizeSeedSceneTestReviewProgress,
  writeSeedSceneTestReview,
  type SeedSceneTestReviewFlags,
  type StoredSeedSceneTestReviewRecord,
} from './audiobook/seedSceneTestReviewUtils'
import { normalizeVoiceCatalogPayload } from './audiobook/voiceCatalog'
import {
  buildSeedSceneReferencePayload,
  isNativeSeedSpeakerModel,
} from './audiobook/seedSceneReferenceUtils'
import { normalizeSeedSceneTestPreviewResponse } from './audiobook/seedSceneTestPreviewUtils'
import { formatSeedSceneTestError } from './audiobook/seedSceneTestErrorUtils'
import { SEED_REFERENCE_VOICE_PREVIEW_TEXT } from './audiobook/voicePreviewText'
import {
  FALLBACK_TTS_MODEL_OPTIONS,
  normalizeTtsModelOptions,
  type TtsModelOption,
} from './audiobook/ttsModels'
import type { TtsModel, VoicePreset } from './audiobook/types'


export interface LatestTtsPreviewReference {
  model: string
  voiceId: string
  audioDataBase64: string
  audioMimeType: string
}

interface SeedSceneTestPanelProps {
  latestTtsPreview: LatestTtsPreviewReference | null
}

const EMPTY_FLAGS: SeedSceneTestReviewFlags = {
  dialogueComplete: null,
  plotUnderstandable: null,
  voicesDistinct: null,
  voiceConsistent: null,
  emotionNatural: null,
  effectsTimed: null,
  musicAppropriate: null,
  mixClear: null,
  usable: null,
}

const REVIEW_ITEMS: Array<{ key: keyof SeedSceneTestReviewFlags; label: string }> = [
  { key: 'dialogueComplete', label: '台词完整' },
  { key: 'plotUnderstandable', label: '剧情可懂' },
  { key: 'voicesDistinct', label: '角色可区分' },
  { key: 'voiceConsistent', label: '音色一致' },
  { key: 'emotionNatural', label: '情绪表演' },
  { key: 'effectsTimed', label: '音效时序' },
  { key: 'musicAppropriate', label: '配乐适配' },
  { key: 'mixClear', label: '混音清晰' },
  { key: 'usable', label: '可用于生产' },
]

const resetReviewEditor = (
  setScore: (value: number | null) => void,
  setFlags: (value: SeedSceneTestReviewFlags) => void,
  setNotes: (value: string) => void,
  setSaved: (value: boolean) => void,
) => {
  setScore(null)
  setFlags(EMPTY_FLAGS)
  setNotes('')
  setSaved(false)
}

const createAudioUrl = (base64: string, mimeType: string) => {
  const binary = window.atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return URL.createObjectURL(new Blob([bytes], { type: mimeType }))
}

const blobToBase64 = async (blob: Blob) => {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  let binary = ''
  const chunkSize = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize))
  }
  return window.btoa(binary)
}

const ReferenceSlotRow = ({
  slot,
  assigned,
  modelOptions,
  latestTtsPreview,
  onAssign,
  onClear,
}: {
  slot: SeedSceneTestReferenceSlot
  assigned: SeedSceneTestReferencePayload | null
  modelOptions: readonly TtsModelOption[]
  latestTtsPreview: LatestTtsPreviewReference | null
  onAssign: (reference: SeedSceneTestReferencePayload) => void
  onClear: () => void
}) => {
  const objectAudioUrlRef = useRef<string | null>(null)
  const [selectedModel, setSelectedModel] = useState<TtsModel>(
    assigned?.source_model || modelOptions[0]?.id || '',
  )
  const [voices, setVoices] = useState<VoicePreset[]>([])
  const [selectedVoiceId, setSelectedVoiceId] = useState(assigned?.source_voice_id || '')
  const [voiceLoading, setVoiceLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewAudioUrl, setPreviewAudioUrl] = useState<string | null>(null)
  const [slotError, setSlotError] = useState<string | null>(null)

  const selectedVoice = voices.find((voice) => voice.id === selectedVoiceId) ?? null
  const usesNativeSpeaker = isNativeSeedSpeakerModel(selectedModel)

  const replacePreviewAudioUrl = (nextUrl: string | null, objectUrl = false) => {
    if (objectAudioUrlRef.current) URL.revokeObjectURL(objectAudioUrlRef.current)
    objectAudioUrlRef.current = objectUrl ? nextUrl : null
    setPreviewAudioUrl(nextUrl)
  }

  useEffect(() => () => {
    if (objectAudioUrlRef.current) URL.revokeObjectURL(objectAudioUrlRef.current)
  }, [])

  useEffect(() => {
    if (!selectedModel && modelOptions[0]?.id) setSelectedModel(modelOptions[0].id)
  }, [modelOptions, selectedModel])

  useEffect(() => {
    if (!assigned) return
    setSelectedModel(assigned.source_model)
    setSelectedVoiceId(assigned.source_voice_id)
  }, [assigned])

  useEffect(() => {
    if (!selectedModel) return
    let active = true
    const loadVoices = async () => {
      setVoiceLoading(true)
      setSlotError(null)
      try {
        const response = await apiClient.getTtsVoices(selectedModel)
        if (!active) return
        const available = normalizeVoiceCatalogPayload(selectedModel, response.data).voices
          .filter((voice) => !voice.disabled)
        setVoices(available)
        setSelectedVoiceId((current) => (
          available.some((voice) => voice.id === current) ? current : (available[0]?.id || '')
        ))
      } catch (requestError) {
        if (!active) return
        setVoices([])
        setSelectedVoiceId('')
        setSlotError(await extractApiErrorMessage(requestError, '加载音色失败'))
      } finally {
        if (active) setVoiceLoading(false)
      }
    }
    void loadVoices()
    return () => { active = false }
  }, [selectedModel])

  const handleModelChange = (model: TtsModel) => {
    setSelectedModel(model)
    setSelectedVoiceId('')
    replacePreviewAudioUrl(null)
    setSlotError(null)
    if (assigned) onClear()
  }

  const handleVoiceChange = (voiceId: string) => {
    setSelectedVoiceId(voiceId)
    replacePreviewAudioUrl(null)
    setSlotError(null)
    if (assigned) onClear()
  }

  const handlePreviewAndAssign = async () => {
    if (!selectedModel || !selectedVoiceId) return
    setPreviewLoading(true)
    setSlotError(null)
    try {
      const result = await apiClient.previewTTSCached({
        text: SEED_REFERENCE_VOICE_PREVIEW_TEXT,
        voice_id: selectedVoiceId,
        model: selectedModel,
        volume: selectedVoice?.default_params?.volume ?? 50,
        speed: selectedVoice?.default_params?.speed ?? 1,
        pitch: selectedVoice?.default_params?.pitch ?? 50,
      })
      if (result.audioUrl) {
        onAssign(buildSeedSceneReferencePayload({
          slotId: slot.id,
          model: selectedModel,
          voiceId: selectedVoiceId,
          audioUrl: result.audioUrl,
        }))
        replacePreviewAudioUrl(result.audioUrl)
      } else if (result.blob) {
        onAssign(buildSeedSceneReferencePayload({
          slotId: slot.id,
          model: selectedModel,
          voiceId: selectedVoiceId,
          audioDataBase64: await blobToBase64(result.blob),
          audioMimeType: result.blob.type || 'audio/mpeg',
        }))
        replacePreviewAudioUrl(URL.createObjectURL(result.blob), true)
      } else {
        throw new Error('试听接口没有返回可用音频')
      }
    } catch (requestError) {
      setSlotError(await extractApiErrorMessage(requestError, '生成或加载试听失败'))
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleAssignLatestPreview = () => {
    if (!latestTtsPreview) return
    onAssign(buildSeedSceneReferencePayload({
      slotId: slot.id,
      model: latestTtsPreview.model,
      voiceId: latestTtsPreview.voiceId,
      audioDataBase64: latestTtsPreview.audioDataBase64,
      audioMimeType: latestTtsPreview.audioMimeType,
    }))
    replacePreviewAudioUrl(createAudioUrl(
      latestTtsPreview.audioDataBase64,
      latestTtsPreview.audioMimeType,
    ), true)
  }

  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 1 }}>
      <Stack spacing={1.25}>
        <Stack direction="row" spacing={1} alignItems="flex-start">
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="body2" sx={{ fontWeight: 700 }}>{slot.speaker}</Typography>
            <Typography variant="caption" color="text.secondary">{slot.description}</Typography>
          </Box>
          {assigned && (
            <Tooltip title="清除 reference">
              <IconButton size="small" onClick={onClear}><DeleteOutlineIcon fontSize="small" /></IconButton>
            </Tooltip>
          )}
        </Stack>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
          <FormControl size="small" sx={{ minWidth: { sm: 190 } }}>
            <InputLabel id={`${slot.id}-model-label`}>模型</InputLabel>
            <Select
              labelId={`${slot.id}-model-label`}
              label="模型"
              value={selectedModel}
              onChange={(event) => handleModelChange(event.target.value)}
            >
              {modelOptions.map((option) => (
                <MenuItem key={option.id} value={option.id}>{option.name}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 0, flex: 1 }} disabled={voiceLoading || !selectedModel}>
            <InputLabel id={`${slot.id}-voice-label`}>{voiceLoading ? '加载中...' : '音色'}</InputLabel>
            <Select
              labelId={`${slot.id}-voice-label`}
              label={voiceLoading ? '加载中...' : '音色'}
              value={selectedVoiceId}
              onChange={(event) => handleVoiceChange(event.target.value)}
            >
              {voices.map((voice) => (
                <MenuItem key={voice.id} value={voice.id}>{voice.label || voice.speaker}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Tooltip title={usesNativeSpeaker ? '试听并绑定为原生 speaker' : '试听并绑定为音频 reference'}>
            <span>
              <IconButton
                color="primary"
                disabled={previewLoading || voiceLoading || !selectedVoiceId}
                onClick={() => void handlePreviewAndAssign()}
                aria-label={`试听并绑定${slot.speaker}音色`}
              >
                {previewLoading ? <CircularProgress size={20} /> : <PlayArrowIcon />}
              </IconButton>
            </span>
          </Tooltip>
          <Button
            size="small"
            variant="text"
            disabled={latestTtsPreview === null}
            onClick={handleAssignLatestPreview}
            sx={{ whiteSpace: 'nowrap' }}
          >
            使用当前试听
          </Button>
        </Stack>

        {assigned && (
          <Chip
            size="small"
            color="success"
            variant="outlined"
            label={`已绑定：${assigned.source_model} · ${assigned.source_voice_id}${isNativeSeedSpeakerModel(assigned.source_model) ? ' · 原生 speaker' : ' · 音频 reference'}`}
            sx={{ alignSelf: 'flex-start', maxWidth: '100%' }}
          />
        )}
        {previewAudioUrl && <Box component="audio" src={previewAudioUrl} controls autoPlay sx={{ width: '100%', height: 34 }} />}
        {slotError && <Alert severity="error">{slotError}</Alert>}
      </Stack>
    </Paper>
  )
}

interface SceneReviewEditorProps {
  score: number | null
  flags: SeedSceneTestReviewFlags
  notes: string
  saved: boolean
  canSave: boolean
  onScoreChange: (value: number | null) => void
  onFlagChange: (key: keyof SeedSceneTestReviewFlags, value: boolean | null) => void
  onNotesChange: (value: string) => void
  onSave: () => void
}

const SceneReviewEditor = ({
  score,
  flags,
  notes,
  saved,
  canSave,
  onScoreChange,
  onFlagChange,
  onNotesChange,
  onSave,
}: SceneReviewEditorProps) => (
  <Stack spacing={1.5}>
    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>试听评审</Typography>
    <Stack direction="row" alignItems="center" justifyContent="space-between">
      <Typography variant="body2">综合评分</Typography>
      <Rating value={score} precision={0.5} onChange={(_, value) => onScoreChange(value)} />
    </Stack>
    {REVIEW_ITEMS.map((item) => (
      <Stack key={item.key} direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
        <Typography variant="body2">{item.label}</Typography>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={flags[item.key] === null ? 'pending' : flags[item.key] ? 'pass' : 'fail'}
          onChange={(_, value: 'pending' | 'pass' | 'fail' | null) => {
            if (value) onFlagChange(item.key, value === 'pending' ? null : value === 'pass')
          }}
          sx={{ '& .MuiToggleButton-root': { px: 1, py: 0.4 } }}
        >
          <ToggleButton value="pending">待评</ToggleButton>
          <ToggleButton value="pass" color="success">通过</ToggleButton>
          <ToggleButton value="fail" color="error">未通过</ToggleButton>
        </ToggleButtonGroup>
      </Stack>
    ))}
    <TextField label="评审备注" multiline minRows={3} value={notes} onChange={(event) => onNotesChange(event.target.value)} />
    <Button
      variant="contained"
      startIcon={<SaveIcon />}
      onClick={onSave}
      color={saved ? 'success' : 'primary'}
      disabled={!canSave}
    >
      {saved ? '已保存' : '保存评审'}
    </Button>
  </Stack>
)

const SeedSceneTestPanel = ({ latestTtsPreview }: SeedSceneTestPanelProps) => {
  const audioUrlRef = useRef<string | null>(null)
  const [cases, setCases] = useState<SeedSceneTestCase[]>([])
  const [selectedCaseId, setSelectedCaseId] = useState('')
  const [selectedVariantId, setSelectedVariantId] = useState('described_voices')
  const [sampleIndex, setSampleIndex] = useState(1)
  const [references, setReferences] = useState<Record<string, SeedSceneTestReferencePayload>>({})
  const [ttsModelOptions, setTtsModelOptions] = useState<readonly TtsModelOption[]>(FALLBACK_TTS_MODEL_OPTIONS)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [preview, setPreview] = useState<SeedSceneTestPreviewResponse | null>(null)
  const [reviews, setReviews] = useState<StoredSeedSceneTestReviewRecord[]>(() => readSeedSceneTestReviews(window.localStorage))
  const [score, setScore] = useState<number | null>(null)
  const [flags, setFlags] = useState<SeedSceneTestReviewFlags>(EMPTY_FLAGS)
  const [notes, setNotes] = useState('')
  const [saved, setSaved] = useState(false)

  const selectedCase = useMemo(
    () => cases.find((item) => item.id === selectedCaseId) ?? null,
    [cases, selectedCaseId],
  )
  const selectedVariant = useMemo(
    () => selectedCase?.variants.find((item) => item.id === selectedVariantId) ?? null,
    [selectedCase, selectedVariantId],
  )
  const totalSamples = cases.reduce(
    (total, item) => total + item.variants.length * (item.repeat_count || 3),
    0,
  )
  const progress = useMemo(
    () => summarizeSeedSceneTestReviewProgress(reviews, totalSamples),
    [reviews, totalSamples],
  )
  const missingReferenceSlots = useMemo(
    () => selectedVariantId === 'reference_voices'
      ? (selectedCase?.reference_slots ?? []).filter((slot) => !references[slot.id])
      : [],
    [references, selectedCase, selectedVariantId],
  )

  const replaceAudioUrl = (nextUrl: string | null) => {
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
    audioUrlRef.current = nextUrl
    setAudioUrl(nextUrl)
  }

  useEffect(() => () => {
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
  }, [])

  useEffect(() => {
    let active = true
    const loadCases = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await apiClient.getSeedSceneTestCases()
        if (!active) return
        const nextCases = response.data.cases ?? []
        setCases(nextCases)
        setSelectedCaseId(nextCases[0]?.id ?? '')
      } catch (requestError) {
        if (active) setError(await extractApiErrorMessage(requestError, '加载场景测试用例失败'))
      } finally {
        if (active) setLoading(false)
      }
    }
    void loadCases()
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    const loadModels = async () => {
      try {
        const response = await apiClient.getTtsModels()
        if (active) setTtsModelOptions(normalizeTtsModelOptions(response.data))
      } catch {
        if (active) setTtsModelOptions(FALLBACK_TTS_MODEL_OPTIONS)
      }
    }
    void loadModels()
    return () => { active = false }
  }, [])

  useEffect(() => {
    replaceAudioUrl(null)
    setPreview(null)
    setPreviewError(null)
    setReferences({})
    setSampleIndex(1)
  }, [selectedCaseId])

  useEffect(() => {
    replaceAudioUrl(null)
    setPreview(null)
    setPreviewError(null)
    setSaved(false)
    if (!selectedCase) return
    const reviewId = buildSeedSceneTestReviewId(
      selectedCase.id,
      selectedVariantId,
      sampleIndex,
    )
    const record = reviews.find((item) => item.id === reviewId)
    setScore(record?.score ?? null)
    setFlags(record?.flags ?? EMPTY_FLAGS)
    setNotes(record?.notes ?? '')
  }, [selectedCase, selectedVariantId, sampleIndex])

  const handleAssignReference = (
    slot: SeedSceneTestReferenceSlot,
    reference: SeedSceneTestReferencePayload,
  ) => {
    replaceAudioUrl(null)
    setPreview(null)
    resetReviewEditor(setScore, setFlags, setNotes, setSaved)
    setReferences((current) => ({
      ...current,
      [slot.id]: reference,
    }))
  }

  const handleClearReference = (slotId: string) => {
    replaceAudioUrl(null)
    setPreview(null)
    resetReviewEditor(setScore, setFlags, setNotes, setSaved)
    setReferences((current) => {
      const next = { ...current }
      delete next[slotId]
      return next
    })
  }

  const handlePreview = async (forceRegenerate = false) => {
    if (!selectedCase || !selectedVariant || missingReferenceSlots.length > 0) return
    setGenerating(true)
    setPreviewError(null)
    try {
      const response = await apiClient.previewSeedSceneTestCase({
        case_id: selectedCase.id,
        variant: selectedVariant.id,
        sample_index: sampleIndex,
        references: selectedVariant.id === 'reference_voices'
          ? selectedCase.reference_slots.map((slot) => references[slot.id])
          : [],
        force_regenerate: forceRegenerate,
      })
      const normalizedPreview = normalizeSeedSceneTestPreviewResponse(
        response.data,
        sampleIndex,
      )
      const reviewId = buildSeedSceneTestReviewId(
        selectedCase.id,
        selectedVariant.id,
        sampleIndex,
      )
      const storedReview = reviews.find((item) => item.id === reviewId)
      if (storedReview && storedReview.generation.sampleId !== normalizedPreview.sample_id) {
        resetReviewEditor(setScore, setFlags, setNotes, setSaved)
      }
      setPreview(normalizedPreview)
      replaceAudioUrl(createAudioUrl(
        normalizedPreview.audio_data_base64,
        normalizedPreview.audio_mime_type,
      ))
    } catch (requestError) {
      setPreviewError(formatSeedSceneTestError(
        await extractApiErrorMessage(requestError, '生成场景样本失败'),
      ))
    } finally {
      setGenerating(false)
    }
  }

  const handleSaveReview = () => {
    if (!selectedCase || !selectedVariant || !preview) return
    if (score === null || Object.values(flags).some((value) => value === null)) return
    writeSeedSceneTestReview(window.localStorage, {
      caseId: selectedCase.id,
      variant: selectedVariant.id,
      sampleIndex,
      score,
      flags,
      generation: {
        sampleId: preview.sample_id,
        durationS: preview.duration ?? null,
        latencyS: preview.generation_latency_s ?? null,
        costYuan: preview.billing.actual_cost_yuan ?? null,
        requestId: preview.request_id ?? null,
        qualityPassed: typeof preview.quality_report.passed === 'boolean'
          ? preview.quality_report.passed
          : null,
        fallbackReason: preview.fallback_reason ?? null,
      },
      notes: notes.trim(),
      updatedAt: new Date().toISOString(),
    })
    setReviews(readSeedSceneTestReviews(window.localStorage))
    setSaved(true)
  }

  const reviewEditorProps: SceneReviewEditorProps = {
    score,
    flags,
    notes,
    saved,
    canSave: preview !== null
      && score !== null
      && Object.values(flags).every((value) => value !== null),
    onScoreChange: (value) => { setScore(value); setSaved(false) },
    onFlagChange: (key, value) => {
      setFlags((current) => ({ ...current, [key]: value }))
      setSaved(false)
    },
    onNotesChange: (value) => { setNotes(value); setSaved(false) },
    onSave: handleSaveReview,
  }

  const handleExportReviews = () => {
    const payload = buildSeedSceneTestReviewExport(reviews)
    const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `seed-scene-reviews-${new Date().toISOString().slice(0, 10)}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return <Box sx={{ minHeight: 420, display: 'grid', placeItems: 'center' }}><CircularProgress /></Box>
  }
  if (error) return <Box sx={{ p: 3 }}><Alert severity="error">{error}</Alert></Box>

  return (
    <Box sx={{
      display: 'grid',
      gridTemplateColumns: { xs: '1fr', md: '260px minmax(380px, 1fr)', xl: '260px minmax(440px, 1fr) 390px' },
      minHeight: 'calc(100vh - 67px)',
    }}>
      <Box component="nav" sx={{ bgcolor: 'white', borderRight: { md: '1px solid #dce1e5' }, p: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography variant="overline" color="text.secondary">场景</Typography>
          <Stack direction="row" spacing={0.5} alignItems="center">
            <Chip size="small" label={`${progress.reviewed}/${progress.total}`} />
            <Tooltip title="导出评审数据">
              <span>
                <IconButton
                  size="small"
                  disabled={reviews.length === 0}
                  onClick={handleExportReviews}
                  aria-label="导出评审数据"
                >
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
          </Stack>
        </Stack>
        <LinearProgress variant="determinate" value={progress.percent} sx={{ mt: 1, mb: 1.5 }} />
        <Stack spacing={0.75}>
          {cases.map((item) => (
            <Button
              key={item.id}
              variant={item.id === selectedCaseId ? 'contained' : 'text'}
              color={item.id === selectedCaseId ? 'primary' : 'inherit'}
              onClick={() => setSelectedCaseId(item.id)}
              sx={{ justifyContent: 'flex-start', textAlign: 'left', minHeight: 48, px: 1.25 }}
            >
              <Box sx={{ minWidth: 0 }}>
                <Typography component="span" variant="body2" sx={{ display: 'block', fontWeight: 700 }}>{item.name}</Typography>
                <Typography component="span" variant="caption" sx={{ color: 'inherit', opacity: 0.72 }}>{item.category}</Typography>
              </Box>
            </Button>
          ))}
        </Stack>
      </Box>

      <Box component="main" sx={{ p: { xs: 2, lg: 3 }, minWidth: 0, borderRight: { xl: '1px solid #dce1e5' } }}>
        {selectedCase && selectedVariant ? (
          <Stack spacing={2.25}>
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography variant="h5" sx={{ fontWeight: 700 }}>{selectedCase.name}</Typography>
                <Chip size="small" label={selectedCase.model} />
                <Chip size="small" variant="outlined" label={`约 ${selectedCase.expected_duration_s} 秒`} />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>{selectedCase.purpose}</Typography>
            </Box>

            <ToggleButtonGroup
              exclusive
              size="small"
              value={selectedVariantId}
              onChange={(_, value: string | null) => { if (value) setSelectedVariantId(value) }}
            >
              {selectedCase.variants.map((variant) => (
                <ToggleButton key={variant.id} value={variant.id}>{variant.blind_label}</ToggleButton>
              ))}
            </ToggleButtonGroup>

            <ToggleButtonGroup
              exclusive
              size="small"
              value={sampleIndex}
              onChange={(_, value: number | null) => { if (value) setSampleIndex(value) }}
              aria-label="复测序号"
            >
              {Array.from({ length: selectedCase.repeat_count || 3 }, (_, index) => index + 1).map((value) => (
                <ToggleButton key={value} value={value}>第 {value} 次</ToggleButton>
              ))}
            </ToggleButtonGroup>

            {selectedVariantId === 'reference_voices' && (
              <Stack spacing={1}>
                {selectedCase.reference_slots.map((slot) => (
                  <ReferenceSlotRow
                    key={`${selectedCase.id}:${slot.id}`}
                    slot={slot}
                    assigned={references[slot.id] ?? null}
                    modelOptions={ttsModelOptions}
                    latestTtsPreview={latestTtsPreview}
                    onAssign={(reference) => handleAssignReference(slot, reference)}
                    onClear={() => handleClearReference(slot.id)}
                  />
                ))}
              </Stack>
            )}

            <Paper variant="outlined" sx={{ p: 2, borderRadius: 1 }}>
              <Typography variant="caption" color="text.secondary">最终场景 Prompt</Typography>
              <Box component="pre" sx={{ m: 0, mt: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontFamily: 'Consolas, monospace', fontSize: 12, lineHeight: 1.65 }}>
                {selectedVariant.prompt}
              </Box>
            </Paper>

            {missingReferenceSlots.length > 0 && (
              <Alert severity="warning">缺少 reference：{missingReferenceSlots.map((slot) => slot.speaker).join('、')}</Alert>
            )}
            {previewError && <Alert severity="error">{previewError}</Alert>}

            <Stack direction="row" spacing={1} alignItems="center">
              <Button
                variant="contained"
                startIcon={generating ? <CircularProgress size={17} color="inherit" /> : <PlayArrowIcon />}
                disabled={generating || missingReferenceSlots.length > 0}
                onClick={() => void handlePreview(false)}
              >
                {generating ? '生成中...' : '生成样本'}
              </Button>
              <Tooltip title="忽略当前复测缓存并重新生成，会产生新的供应商费用">
                <span>
                  <IconButton disabled={generating || missingReferenceSlots.length > 0} onClick={() => void handlePreview(true)}>
                    <RefreshIcon />
                  </IconButton>
                </span>
              </Tooltip>
              {preview?.cached && <Chip size="small" color="success" label="已复用缓存" />}
            </Stack>

            {audioUrl && preview && (
              <Paper variant="outlined" sx={{ p: 2, borderRadius: 1 }}>
                <Box component="audio" src={audioUrl} controls autoPlay sx={{ width: '100%', display: 'block' }} />
                <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                  <Chip size="small" label={`${preview.duration?.toFixed(1) ?? '--'} 秒`} />
                  <Chip size="small" label={`第 ${preview.sample_index} 次`} />
                  {preview.generation_latency_s !== null && preview.generation_latency_s !== undefined && (
                    <Chip size="small" label={`生成 ${preview.generation_latency_s.toFixed(1)} 秒`} />
                  )}
                  {preview.billing.actual_cost_yuan !== null && preview.billing.actual_cost_yuan !== undefined && (
                    <Chip size="small" label={`公开价 ¥${preview.billing.actual_cost_yuan.toFixed(4)}`} />
                  )}
                  <Chip size="small" label={`${Math.max(1, Math.round(preview.audio_size_bytes / 1024))} KB`} />
                  <Chip size="small" color={preview.quality_report.passed === true ? 'success' : 'warning'} label={preview.quality_report.passed === true ? '自动检查通过' : '需要人工复核'} />
                </Stack>
                {preview.fallback_reason && <Alert severity="warning" sx={{ mt: 1 }}>{preview.fallback_reason}</Alert>}
              </Paper>
            )}

            <Box sx={{ display: { xl: 'none' } }}>
              <Divider sx={{ mb: 2.5 }} />
              <SceneReviewEditor {...reviewEditorProps} />
            </Box>
          </Stack>
        ) : <Alert severity="info">没有可用场景测试项。</Alert>}
      </Box>

      <Box component="aside" sx={{ display: { xs: 'none', xl: 'block' }, bgcolor: 'white', p: 2.5, minWidth: 0 }}>
        <SceneReviewEditor {...reviewEditorProps} />
      </Box>
    </Box>
  )
}

export default SeedSceneTestPanel
