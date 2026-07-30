import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Alert, Box, Button, Chip, CircularProgress, Divider, FormControl, IconButton,
  InputLabel, LinearProgress, MenuItem, Paper, Rating, Select, Stack, TextField,
  ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import SaveIcon from '@mui/icons-material/Save'
import ScienceIcon from '@mui/icons-material/Science'

import SeedSceneTestPanel, { type LatestTtsPreviewReference } from './SeedSceneTestPanel'
import SeedSceneBlindReviewPanel from './SeedSceneBlindReviewPanel'
import {
  apiClient,
  extractApiErrorMessage,
  type TtsPromptTestCase,
  type TtsPromptTestModel,
  type TtsPromptTestProviderPromptSnapshot,
} from '@/services/api'
import { normalizeVoiceCatalogPayload } from './audiobook/voiceCatalog'
import type { VoicePreset } from './audiobook/types'
import {
  buildTtsPromptTestReviewId,
  readTtsPromptTestReviews,
  summarizeTtsPromptTestReviewProgress,
  writeTtsPromptTestReview,
  type StoredTtsPromptTestReviewRecord,
  type TtsPromptTestReviewFlags,
} from './audiobook/ttsPromptTestReviewUtils'

const EMPTY_FLAGS: TtsPromptTestReviewFlags = {
  emotionChanged: null,
  pauseHandled: null,
  stressHandled: null,
  noTagLeak: null,
  usable: null,
}

const REVIEW_ITEMS: Array<{ key: keyof TtsPromptTestReviewFlags; label: string }> = [
  { key: 'emotionChanged', label: '情绪变化' },
  { key: 'pauseHandled', label: '停顿处理' },
  { key: 'stressHandled', label: '重读处理' },
  { key: 'noTagLeak', label: '无标签泄漏' },
  { key: 'usable', label: '可用于生产' },
]

const createAudioUrl = (base64: string, mimeType: string) => {
  const binary = window.atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return URL.createObjectURL(new Blob([bytes], { type: mimeType }))
}

const PromptBlock = ({ title, value }: { title: string; value: unknown }) => {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  if (!text || text === '[]' || text === '{}') return null
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>{title}</Typography>
      <Box component="pre" sx={{
        m: 0, p: 1.25, maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
        bgcolor: '#f6f7f9', border: '1px solid #e2e5e9', borderRadius: 1,
        fontFamily: 'Consolas, monospace', fontSize: 12, lineHeight: 1.55,
      }}>
        {text}
      </Box>
    </Box>
  )
}

const PromptInspector = ({ snapshot }: { snapshot: TtsPromptTestProviderPromptSnapshot | null }) => (
  <Stack spacing={1.5}>
    <Stack direction="row" alignItems="center" justifyContent="space-between">
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>最终供应商提示词</Typography>
      {snapshot && <Chip size="small" label={snapshot.mode} />}
    </Stack>
    {snapshot ? (
      <>
        <PromptBlock title="instructions" value={snapshot.provider_prompt.instructions} />
        <PromptBlock title="messages" value={snapshot.provider_prompt.messages} />
        <PromptBlock title="text_prefix" value={snapshot.provider_prompt.text_prefix} />
        <PromptBlock title="context_texts" value={snapshot.provider_prompt.context_texts} />
        <PromptBlock title="inline_tag_strategy" value={snapshot.provider_prompt.inline_tag_strategy ?? {}} />
        <PromptBlock title="delivery_plan" value={snapshot.delivery_plan} />
        <PromptBlock title="budget" value={snapshot.budget} />
        {snapshot.warnings?.map((warning) => <Alert key={warning} severity="warning">{warning}</Alert>)}
      </>
    ) : <Typography variant="body2" color="text.secondary">暂无提示词快照。</Typography>}
  </Stack>
)

interface ReviewEditorProps {
  score: number | null
  flags: TtsPromptTestReviewFlags
  notes: string
  saved: boolean
  onScoreChange: (value: number | null) => void
  onFlagChange: (key: keyof TtsPromptTestReviewFlags, value: boolean | null) => void
  onNotesChange: (value: string) => void
  onSave: () => void
}

const ReviewEditor = ({
  score, flags, notes, saved, onScoreChange, onFlagChange, onNotesChange, onSave,
}: ReviewEditorProps) => (
  <Stack spacing={1.5}>
    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>试听评审</Typography>
    <Stack direction="row" alignItems="center" justifyContent="space-between">
      <Typography variant="body2">综合评分</Typography>
      <Rating value={score} onChange={(_, value) => onScoreChange(value)} />
    </Stack>
    {REVIEW_ITEMS.map((item) => (
      <Stack key={item.key} direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
        <Typography variant="body2">{item.label}</Typography>
        <ToggleButtonGroup
          exclusive size="small"
          value={flags[item.key] === null ? 'pending' : flags[item.key] ? 'pass' : 'fail'}
          onChange={(_, value: 'pending' | 'pass' | 'fail' | null) => {
            if (value) onFlagChange(item.key, value === 'pending' ? null : value === 'pass')
          }}
          sx={{ '& .MuiToggleButton-root': { px: 1.25, py: 0.5 } }}
        >
          <ToggleButton value="pending">待评</ToggleButton>
          <ToggleButton value="pass" color="success">通过</ToggleButton>
          <ToggleButton value="fail" color="error">未通过</ToggleButton>
        </ToggleButtonGroup>
      </Stack>
    ))}
    <TextField label="评审备注" value={notes} onChange={(event) => onNotesChange(event.target.value)} multiline minRows={3} fullWidth />
    <Button variant="contained" startIcon={<SaveIcon />} onClick={onSave} color={saved ? 'success' : 'primary'}>
      {saved ? '已保存' : '保存评审'}
    </Button>
  </Stack>
)

const TtsPromptTestPage = () => {
  const [searchParams] = useSearchParams()
  const blindBatchId = searchParams.get('blind_batch_id')?.trim() || ''
  const navigate = useNavigate()
  const audioUrlRef = useRef<string | null>(null)
  const [testMode, setTestMode] = useState<'tts' | 'seed_scene'>('tts')
  const [latestTtsPreview, setLatestTtsPreview] = useState<LatestTtsPreviewReference | null>(null)
  const [models, setModels] = useState<TtsPromptTestModel[]>([])
  const [selectedModelId, setSelectedModelId] = useState('')
  const [selectedCaseId, setSelectedCaseId] = useState('')
  const [voices, setVoices] = useState<VoicePreset[]>([])
  const [selectedVoiceId, setSelectedVoiceId] = useState('')
  const [loading, setLoading] = useState(true)
  const [voiceLoading, setVoiceLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [previewMeta, setPreviewMeta] = useState<string | null>(null)
  const [previewSnapshot, setPreviewSnapshot] = useState<TtsPromptTestProviderPromptSnapshot | null>(null)
  const [reviews, setReviews] = useState<StoredTtsPromptTestReviewRecord[]>(() => readTtsPromptTestReviews(window.localStorage))
  const [score, setScore] = useState<number | null>(null)
  const [flags, setFlags] = useState<TtsPromptTestReviewFlags>(EMPTY_FLAGS)
  const [notes, setNotes] = useState('')
  const [saved, setSaved] = useState(false)

  const selectedModel = useMemo(() => models.find((model) => model.model === selectedModelId) ?? null, [models, selectedModelId])
  const selectedCase = useMemo<TtsPromptTestCase | null>(
    () => selectedModel?.cases.find((item) => item.id === selectedCaseId) ?? null,
    [selectedCaseId, selectedModel],
  )
  const totalCases = useMemo(() => models.reduce((total, model) => total + model.cases.length, 0), [models])
  const progress = useMemo(() => summarizeTtsPromptTestReviewProgress(reviews, totalCases), [reviews, totalCases])
  const displayedSnapshot = previewSnapshot ?? selectedCase?.provider_prompt_snapshot ?? null

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
        const response = await apiClient.getTtsPromptTestCases()
        if (!active) return
        const nextModels = response.data.models ?? []
        setModels(nextModels)
        setSelectedModelId(nextModels[0]?.model ?? '')
        setSelectedCaseId(nextModels[0]?.cases[0]?.id ?? '')
      } catch (requestError) {
        if (active) setError(await extractApiErrorMessage(requestError, '加载 TTS 测试用例失败'))
      } finally {
        if (active) setLoading(false)
      }
    }
    void loadCases()
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!selectedModelId) return
    let active = true
    const loadVoices = async () => {
      setVoiceLoading(true)
      setVoiceError(null)
      setSelectedVoiceId('')
      try {
        const response = await apiClient.getTtsVoices(selectedModelId)
        if (!active) return
        const available = normalizeVoiceCatalogPayload(selectedModelId, response.data).voices.filter((voice) => !voice.disabled)
        setVoices(available)
        setSelectedVoiceId(available[0]?.id ?? '')
      } catch (requestError) {
        if (!active) return
        setVoices([])
        setVoiceError(await extractApiErrorMessage(requestError, '加载模型音色失败'))
      } finally {
        if (active) setVoiceLoading(false)
      }
    }
    void loadVoices()
    return () => { active = false }
  }, [selectedModelId])

  useEffect(() => {
    replaceAudioUrl(null)
    setPreviewError(null)
    setPreviewMeta(null)
    setPreviewSnapshot(null)
    setSaved(false)
    if (!selectedCase) return
    const record = reviews.find((item) => item.id === buildTtsPromptTestReviewId(selectedCase.model, selectedCase.id))
    setScore(record?.score ?? null)
    setFlags(record?.flags ?? EMPTY_FLAGS)
    setNotes(record?.notes ?? '')
  }, [selectedCaseId, selectedModelId])

  const handleModelChange = (modelId: string) => {
    const model = models.find((item) => item.model === modelId)
    setSelectedModelId(modelId)
    setSelectedCaseId(model?.cases[0]?.id ?? '')
  }

  const handlePreview = async () => {
    if (!selectedCase || !selectedVoiceId) return
    setPreviewLoading(true)
    setPreviewError(null)
    try {
      const { data } = await apiClient.previewTtsPromptTestCase({
        model: selectedCase.model,
        case_id: selectedCase.id,
        voice_id: selectedVoiceId,
      })
      replaceAudioUrl(createAudioUrl(data.audio_data_base64, data.audio_mime_type))
      setLatestTtsPreview({
        model: data.model,
        voiceId: data.voice_id,
        audioDataBase64: data.audio_data_base64,
        audioMimeType: data.audio_mime_type,
      })
      setPreviewSnapshot(data.provider_prompt_snapshot)
      setPreviewMeta([data.provider, data.provider_model, data.transport, `${Math.max(1, Math.round(data.audio_size_bytes / 1024))} KB`].filter(Boolean).join(' · '))
    } catch (requestError) {
      setPreviewError(await extractApiErrorMessage(requestError, '生成试听失败'))
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleSaveReview = () => {
    if (!selectedCase) return
    writeTtsPromptTestReview(window.localStorage, {
      model: selectedCase.model,
      caseId: selectedCase.id,
      score,
      flags,
      notes: notes.trim(),
      updatedAt: new Date().toISOString(),
    })
    setReviews(readTtsPromptTestReviews(window.localStorage))
    setSaved(true)
  }

  const reviewEditorProps: ReviewEditorProps = {
    score, flags, notes, saved,
    onScoreChange: (value) => { setScore(value); setSaved(false) },
    onFlagChange: (key, value) => { setFlags((current) => ({ ...current, [key]: value })); setSaved(false) },
    onNotesChange: (value) => { setNotes(value); setSaved(false) },
    onSave: handleSaveReview,
  }

  if (blindBatchId) {
    return <SeedSceneBlindReviewPanel batchId={blindBatchId} />
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: '#f3f5f7', color: '#1f2933' }}>
      <Box component="header" sx={{ bgcolor: '#263238', color: 'white', borderBottom: '3px solid #00a389' }}>
        <Box sx={{ minHeight: 64, px: { xs: 2, md: 3 }, py: { xs: 1, sm: 0 }, display: 'flex', flexWrap: { xs: 'wrap', sm: 'nowrap' }, alignItems: 'center', gap: 1.5 }}>
          <Tooltip title="返回有声书项目"><IconButton color="inherit" onClick={() => navigate('/audiobook-dashboard')}><ArrowBackIcon /></IconButton></Tooltip>
          <ScienceIcon sx={{ color: '#52d6c2' }} />
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>音频模型测试</Typography>
            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.72)' }}>
              {testMode === 'tts' ? `${progress.reviewed}/${progress.total} 已评审` : 'Seed Audio 场景 A/B'}
            </Typography>
          </Box>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={testMode}
            onChange={(_, value: 'tts' | 'seed_scene' | null) => { if (value) setTestMode(value) }}
            sx={{
              width: { xs: '100%', sm: 'auto' },
              order: { xs: 3, sm: 0 },
              bgcolor: 'rgba(255,255,255,0.1)',
              '& .MuiToggleButton-root': { color: 'rgba(255,255,255,0.78)', borderColor: 'rgba(255,255,255,0.25)', px: 1.25 },
              '& .MuiToggleButton-root:first-of-type': { flex: { xs: 1, sm: 'initial' } },
              '& .MuiToggleButton-root:last-of-type': { flex: { xs: 1, sm: 'initial' } },
              '& .Mui-selected': { color: '#102a27 !important', bgcolor: '#52d6c2 !important' },
            }}
          >
            <ToggleButton value="tts">TTS 朗读</ToggleButton>
            <ToggleButton value="seed_scene">Seed 场景</ToggleButton>
          </ToggleButtonGroup>
          {testMode === 'tts' && (
            <Box sx={{ display: { xs: 'none', sm: 'block' }, width: 150 }}>
              <LinearProgress variant="determinate" value={progress.percent} color="success" />
            </Box>
          )}
        </Box>
      </Box>

      <Box sx={{ display: testMode === 'tts' ? 'block' : 'none' }}>
        {loading ? (
          <Box sx={{ minHeight: 420, display: 'grid', placeItems: 'center' }}><CircularProgress /></Box>
        ) : error ? (
          <Box sx={{ p: 3 }}><Alert severity="error">{error}</Alert></Box>
        ) : (
          <Box sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: '260px minmax(380px, 1fr)', xl: '260px minmax(440px, 1fr) 390px' },
            minHeight: 'calc(100vh - 67px)',
          }}>
          <Box component="nav" sx={{ bgcolor: 'white', borderRight: { md: '1px solid #dce1e5' }, p: 2 }}>
            <Typography variant="overline" color="text.secondary">模型</Typography>
            <Stack spacing={0.75} sx={{ mt: 1 }}>
              {models.map((model) => {
                const reviewed = model.cases.filter((testCase) => reviews.some((item) => item.id === buildTtsPromptTestReviewId(model.model, testCase.id))).length
                return (
                  <Button key={model.model} variant={model.model === selectedModelId ? 'contained' : 'text'} color={model.model === selectedModelId ? 'primary' : 'inherit'} onClick={() => handleModelChange(model.model)} sx={{ justifyContent: 'space-between', textAlign: 'left', minHeight: 46, px: 1.25 }}>
                    <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{model.name}</Box>
                    <Chip size="small" label={`${reviewed}/${model.cases.length}`} sx={{ ml: 1 }} />
                  </Button>
                )
              })}
            </Stack>
          </Box>

          <Box component="main" sx={{ p: { xs: 2, lg: 3 }, minWidth: 0, borderRight: { xl: '1px solid #dce1e5' } }}>
            {selectedModel && selectedCase ? (
              <Stack spacing={2.5}>
                <Box>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography variant="h5" sx={{ fontWeight: 700 }}>{selectedModel.name}</Typography>
                    <Chip size="small" label={selectedCase.style_control_mode} />
                    {selectedCase.requires_custom_voice && <Chip size="small" color="warning" label="自定义音色" />}
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>{selectedModel.description}</Typography>
                </Box>
                <FormControl size="small" fullWidth>
                  <InputLabel id="test-case-label">测试项</InputLabel>
                  <Select labelId="test-case-label" label="测试项" value={selectedCaseId} onChange={(event) => setSelectedCaseId(event.target.value)}>
                    {selectedModel.cases.map((item) => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
                  </Select>
                </FormControl>
                <Box>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{selectedCase.name}</Typography>
                  <Typography variant="body2" color="text.secondary">{selectedCase.purpose}</Typography>
                </Box>
                <Paper variant="outlined" sx={{ p: 2, borderRadius: 1 }}>
                  <Typography variant="caption" color="text.secondary">测试文本</Typography>
                  <Typography sx={{ mt: 0.75, lineHeight: 1.9 }}>{selectedCase.text}</Typography>
                </Paper>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'flex-start' }}>
                  <FormControl size="small" fullWidth error={Boolean(voiceError)}>
                    <InputLabel id="voice-label">测试音色</InputLabel>
                    <Select labelId="voice-label" label="测试音色" value={selectedVoiceId} disabled={voiceLoading} onChange={(event) => setSelectedVoiceId(event.target.value)}>
                      {voices.map((voice) => <MenuItem key={voice.id} value={voice.id}>{voice.label}</MenuItem>)}
                    </Select>
                  </FormControl>
                  <Button variant="contained" startIcon={previewLoading ? <CircularProgress size={17} color="inherit" /> : <PlayArrowIcon />} disabled={previewLoading || !selectedVoiceId} onClick={handlePreview} sx={{ minWidth: 126, minHeight: 40, whiteSpace: 'nowrap' }}>
                    生成试听
                  </Button>
                </Stack>
                {voiceError && <Alert severity="warning">{voiceError}</Alert>}
                {!voiceLoading && voices.length === 0 && <Alert severity={selectedCase.requires_custom_voice ? 'warning' : 'info'}>当前模型没有可用音色{selectedCase.requires_custom_voice ? '，请先在有声书音色配置中创建对应自定义音色。' : '。'}</Alert>}
                {previewError && <Alert severity="error">{previewError}</Alert>}
                {audioUrl && (
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 1 }}>
                    <Box component="audio" src={audioUrl} controls autoPlay sx={{ width: '100%', display: 'block' }} />
                    {previewMeta && <Typography variant="caption" color="text.secondary">{previewMeta}</Typography>}
                  </Paper>
                )}
                <Box sx={{ display: { xl: 'none' } }}>
                  <PromptInspector snapshot={displayedSnapshot} />
                  <Divider sx={{ my: 2.5 }} />
                  <ReviewEditor {...reviewEditorProps} />
                </Box>
              </Stack>
            ) : <Alert severity="info">没有可用测试项。</Alert>}
          </Box>

          <Box component="aside" sx={{ display: { xs: 'none', xl: 'block' }, bgcolor: 'white', p: 2.5, minWidth: 0 }}>
            <PromptInspector snapshot={displayedSnapshot} />
            <Divider sx={{ my: 2.5 }} />
            <ReviewEditor {...reviewEditorProps} />
          </Box>
          </Box>
        )}
      </Box>
      <Box sx={{ display: testMode === 'seed_scene' ? 'block' : 'none' }}>
        <SeedSceneTestPanel latestTtsPreview={latestTtsPreview} />
      </Box>
    </Box>
  )
}

export default TtsPromptTestPage
