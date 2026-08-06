import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import CloseIcon from '@mui/icons-material/Close'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import MicIcon from '@mui/icons-material/Mic'
import StopIcon from '@mui/icons-material/Stop'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type {
  AudiobookScriptSegmentPayload,
  SegmentDirectionAssistResponse,
  SegmentDirectionCueType,
} from '../../services/api'
import type {
  AudioAssetSelection,
  ScriptSegment,
} from './types'
import AudioPicker from './AudioPicker'
import {
  appendSoundEffectAssetPatch,
  getMusicCueInputValue,
  getSoundEffectsInputValue,
  sanitizeScriptSegmentVoiceIdentityControls,
} from './scriptSegmentCardUtils'

interface SegmentCueEditorDialogProps {
  open: boolean
  cueType: SegmentDirectionCueType | null
  projectId?: number
  chapterId?: number
  segmentIndex: number
  segment: ScriptSegment | null
  ttsModel?: string
  onClose: () => void
  onApplyPatch: (patch: Partial<ScriptSegment>) => void
}

const CUE_LABELS: Record<SegmentDirectionCueType, string> = {
  voice: '人声提示',
  sfx: '音效提示',
  bgm: '配乐提示',
}

const CUE_COLORS: Record<SegmentDirectionCueType, string> = {
  voice: '#2f6df6',
  sfx: '#ff8a2a',
  bgm: '#8b5cf6',
}

const CUE_EXAMPLES: Record<SegmentDirectionCueType, string[]> = {
  voice: [
    '语速缓慢，声音低沉沙哑，重读“痛”字，句尾拖长，营造痛苦氛围。',
    '语气急促慌乱，气息不稳，尾音发颤，表现恐惧与无助。',
    '平静克制地叙述，关键词略微加重，段落结尾留白停顿。',
  ],
  sfx: [
    '水滴声持续循环，底层铺垫，音量较低，淡入 1 秒。',
    '远处闷雷一次，随后铁链拖地声由远及近，音量渐强。',
    '开门吱呀声一次，紧跟轻微回声，突出空间空旷感。',
  ],
  bgm: [
    '低沉弦乐缓慢进入，音量压低，淡入 2 秒，持续跟随情绪。',
    '紧张鼓点渐强，节奏加快，在句尾戛然而止。',
    '空灵钢琴独奏，缓慢淡出 3 秒，留出情绪余韵。',
  ],
}

const MAX_READING_RECORDING_SECONDS = 30

const toDirectionSegmentPayload = (
  segment: ScriptSegment,
): AudiobookScriptSegmentPayload => {
  // 音频路径和缓存字段由服务端管理，不应随提示整理请求回传。
  const {
    audio_path: _audioPath,
    sfx_audio_path: _sfxAudioPath,
    bgm_audio_path: _bgmAudioPath,
    mix_audio_path: _mixAudioPath,
    ...semanticSegment
  } = sanitizeScriptSegmentVoiceIdentityControls(segment)
  return semanticSegment
}

const mergeAssistPatchWithSelectedAsset = (
  cueType: SegmentDirectionCueType,
  segment: ScriptSegment,
  assistPatch: Partial<ScriptSegment>,
  selectedAsset: AudioAssetSelection | null,
  description: string,
): Partial<ScriptSegment> => {
  if (!selectedAsset) return assistPatch
  if (cueType === 'bgm') {
    const suggestedCue = assistPatch.music_cue && typeof assistPatch.music_cue === 'object'
      ? assistPatch.music_cue
      : {}
    return {
      ...assistPatch,
      music_cue: {
        ...suggestedCue,
        asset_id: selectedAsset.id,
        style: suggestedCue.style || description || selectedAsset.style || selectedAsset.label,
        name: suggestedCue.name || selectedAsset.label,
        ...(suggestedCue.mood || !selectedAsset.mood ? {} : { mood: selectedAsset.mood }),
      },
      music_cue_simple: null,
    }
  }
  if (cueType !== 'sfx') return assistPatch

  const existingEffects = Array.isArray(segment.sound_effects) ? segment.sound_effects : []
  const existingSimple = Array.isArray(segment.sound_effects_simple)
    ? segment.sound_effects_simple.filter(Boolean)
    : []
  const suggestedEffects = Array.isArray(assistPatch.sound_effects)
    ? [...assistPatch.sound_effects]
    : []
  if (existingEffects.length === 0 && existingSimple.length === 0 && suggestedEffects.length > 0) {
    const first = suggestedEffects[0]
    if (first && typeof first === 'object') {
      suggestedEffects[0] = {
        ...first,
        asset_id: selectedAsset.id,
        name: first.name || selectedAsset.name || selectedAsset.label,
      }
      return {
        ...assistPatch,
        sound_effects: suggestedEffects,
        sound_effects_simple: [],
      }
    }
  }
  return {
    ...assistPatch,
    ...appendSoundEffectAssetPatch(
      { ...segment, ...assistPatch },
      selectedAsset,
      description,
    ),
  }
}

const SegmentCueEditorDialog = ({
  open,
  cueType,
  projectId,
  chapterId,
  segmentIndex,
  segment,
  ttsModel,
  onClose,
  onApplyPatch,
}: SegmentCueEditorDialogProps) => {
  const [description, setDescription] = useState('')
  const [selectedAsset, setSelectedAsset] = useState<AudioAssetSelection | null>(null)
  const [assistResult, setAssistResult] = useState<SegmentDirectionAssistResponse | null>(null)
  const [assistLoading, setAssistLoading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const readingSessionRef = useRef(0)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const maxTimerRef = useRef<number | null>(null)

  const clearReadingTimer = () => {
    if (maxTimerRef.current !== null) {
      window.clearTimeout(maxTimerRef.current)
      maxTimerRef.current = null
    }
  }

  const stopReadingStream = () => {
    clearReadingTimer()
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }

  // 会话代次递增：关闭/切换片段后丢弃迟到的录音与分析响应
  const abortReadingRecording = useCallback(() => {
    readingSessionRef.current += 1
    const recorder = recorderRef.current
    recorderRef.current = null
    chunksRef.current = []
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    stopReadingStream()
    setRecording(false)
    setAnalyzing(false)
  }, [])

  const handleClose = useCallback(() => {
    abortReadingRecording()
    onClose()
  }, [abortReadingRecording, onClose])

  useEffect(() => {
    abortReadingRecording()
    if (!open || !cueType || !segment) return
    const initialDescription = cueType === 'voice'
      ? String(segment.performance_notes || '')
      : cueType === 'sfx'
        ? getSoundEffectsInputValue(segment)
        : getMusicCueInputValue(segment)
    setDescription(initialDescription)
    setSelectedAsset(null)
    setAssistResult(null)
    setError(null)
  }, [abortReadingRecording, chapterId, cueType, open, projectId, segment?.index, segment?.segment_key, segmentIndex])

  useEffect(() => () => {
    abortReadingRecording()
  }, [abortReadingRecording])

  const handleDescriptionChange = (value: string) => {
    setDescription(value)
    setAssistResult(null)
    setError(null)
  }

  const analyzeReadingRecording = async (blob: Blob) => {
    if (!projectId || !chapterId || !segment) return
    const sessionId = readingSessionRef.current
    setAnalyzing(true)
    setError(null)
    try {
      // 后端用片段台词做一致性校验，并用音频理解模型提取朗读特点
      const formData = new FormData()
      formData.append('file', blob, `reading-${segmentIndex}.webm`)
      if (ttsModel) formData.append('tts_model', ttsModel)
      const response = await apiClient.analyzeSegmentDirectionReading(
        projectId,
        chapterId,
        segmentIndex,
        formData,
      )
      if (sessionId !== readingSessionRef.current) return
      setAssistResult(response.data)
    } catch (caught: unknown) {
      if (sessionId !== readingSessionRef.current) return
      setError(await extractApiErrorMessage(caught, '朗读分析失败，请对照上方文本重新朗读'))
    } finally {
      if (sessionId === readingSessionRef.current) setAnalyzing(false)
    }
  }

  const handleReadingRecording = async () => {
    if (recording) {
      recorderRef.current?.stop()
      return
    }
    if (analyzing || assistLoading) return
    if (!projectId || !chapterId || !segment) {
      setError('章节上下文不可用，无法分析朗读')
      return
    }
    if (!String(segment.text || '').trim()) {
      setError('片段台词为空，无法分析朗读')
      return
    }
    if (
      typeof navigator === 'undefined'
      || !navigator.mediaDevices?.getUserMedia
      || typeof MediaRecorder === 'undefined'
    ) {
      setError('当前浏览器不支持录音，请换用支持麦克风录制的浏览器')
      return
    }
    const sessionId = readingSessionRef.current + 1
    readingSessionRef.current = sessionId
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (sessionId !== readingSessionRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      streamRef.current = stream
      chunksRef.current = []
      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const chunks = chunksRef.current
        chunksRef.current = []
        recorderRef.current = null
        stopReadingStream()
        setRecording(false)
        if (sessionId !== readingSessionRef.current) return
        if (chunks.length === 0) {
          setError('未获取到朗读录音数据，请重试')
          return
        }
        const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' })
        void analyzeReadingRecording(blob)
      }
      recorder.onerror = () => {
        recorderRef.current = null
        chunksRef.current = []
        stopReadingStream()
        setRecording(false)
        if (sessionId === readingSessionRef.current) setError('朗读录制失败，请重试')
      }
      recorder.start()
      setRecording(true)
      maxTimerRef.current = window.setTimeout(() => {
        if (recorderRef.current && recorderRef.current.state !== 'inactive') {
          recorderRef.current.stop()
        }
      }, MAX_READING_RECORDING_SECONDS * 1000)
    } catch (caught: unknown) {
      if (sessionId !== readingSessionRef.current) return
      stopReadingStream()
      setRecording(false)
      setError(await extractApiErrorMessage(caught, '无法访问麦克风，请检查浏览器权限'))
    }
  }

  const handleAssist = async () => {
    if (!cueType || !segment || !projectId || !chapterId || !description.trim()) {
      setError('请先输入提示描述')
      return
    }
    setAssistLoading(true)
    setError(null)
    try {
      const response = await apiClient.assistSegmentDirection(projectId, chapterId, segmentIndex, {
        cue_type: cueType,
        description: description.trim(),
        segment: toDirectionSegmentPayload(segment),
        tts_model: ttsModel,
      })
      setAssistResult(response.data)
    } catch (caught: unknown) {
      setError(await extractApiErrorMessage(caught, '提示整理失败'))
    } finally {
      setAssistLoading(false)
    }
  }

  const buildDirectPatch = (): Partial<ScriptSegment> => {
    if (!cueType) return {}
    if (cueType === 'voice') return { performance_notes: description.trim() }
    if (cueType === 'sfx') {
      if (selectedAsset && segment) {
        return appendSoundEffectAssetPatch(segment, selectedAsset, description.trim())
      }
      return { sound_effects_simple: description.trim() ? [description.trim()] : [], sound_effects: [] }
    }
    if (selectedAsset) {
      return {
        music_cue: {
          asset_id: selectedAsset.id,
          style: description.trim() || selectedAsset.style || selectedAsset.label,
          name: selectedAsset.label,
          ...(selectedAsset.mood ? { mood: selectedAsset.mood } : {}),
        },
        music_cue_simple: null,
      }
    }
    return { music_cue_simple: description.trim() || null, music_cue: null }
  }

  const handleApply = () => {
    const patch = assistResult?.patch && cueType && segment
      ? mergeAssistPatchWithSelectedAsset(
        cueType,
        segment,
        assistResult.patch as Partial<ScriptSegment>,
        selectedAsset,
        description.trim(),
      )
      : buildDirectPatch()
    onApplyPatch(sanitizeScriptSegmentVoiceIdentityControls(patch as Partial<ScriptSegment>))
    handleClose()
  }

  if (!cueType || !segment) return null
  const title = CUE_LABELS[cueType]
  const color = CUE_COLORS[cueType]
  const canAssist = Boolean(projectId && chapterId && description.trim())
  const intentEntries = Object.entries(assistResult?.intent || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
  const model_capabilities = assistResult?.model_capabilities
  const canApply = Boolean(description.trim() || selectedAsset || assistResult)

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullWidth
      maxWidth="sm"
      PaperProps={{
        sx: {
          bgcolor: '#17191f',
          color: '#f4f7fb',
          border: '1px solid rgba(255,255,255,0.12)',
          borderTop: `3px solid ${color}`,
          borderRadius: 1,
        },
      }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>{title}</Typography>
          <Typography variant="caption" sx={{ color: '#9aa4b2' }}>片段 #{segmentIndex + 1}</Typography>
        </Box>
        <Tooltip title="关闭">
          <IconButton aria-label="关闭提示编辑" onClick={handleClose}><CloseIcon /></IconButton>
        </Tooltip>
      </DialogTitle>
      <DialogContent dividers sx={{ borderColor: 'rgba(255,255,255,0.08)' }}>
        <Stack spacing={1.5}>
          {cueType === 'voice' && String(segment.text || '').trim() && (
            <Box
              aria-label="要朗读的文本"
              sx={{
                px: 1.25,
                py: 1,
                borderRadius: 1,
                border: '1px solid rgba(47,109,246,0.35)',
                bgcolor: 'rgba(47,109,246,0.08)',
              }}
            >
              <Typography variant="caption" sx={{ display: 'block', color: '#9aa4b2', mb: 0.5 }}>
                要朗读的文本{segment.speaker ? `（${segment.speaker}）` : ''}
              </Typography>
              <Typography variant="body2" sx={{ color: '#f4f7fb', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                {String(segment.text || '').trim()}
              </Typography>
            </Box>
          )}
          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5 }}>
            <Typography variant="caption" sx={{ color: '#9aa4b2' }}>
              {cueType === 'voice' ? '表演描述' : '声音设计描述'}
            </Typography>
            <Tooltip title="用户输入保留为语义字段；供应商运行时参数由服务端重新编译。">
              <InfoOutlinedIcon sx={{ fontSize: 16, color: '#9aa4b2' }} />
            </Tooltip>
          </Box>
          <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'flex-start' }}>
            <TextField
              fullWidth
              multiline
              minRows={4}
              maxRows={10}
              value={description}
              onChange={(event) => handleDescriptionChange(event.target.value)}
              placeholder={cueType === 'voice'
                ? '例如：语速缓慢，重读“痛”字，句尾拖长，营造压抑感。'
                : cueType === 'sfx'
                  ? '例如：近距离持续水滴声，底层，音量较低。'
                  : '例如：低沉弦乐缓慢进入，保持压抑，淡入 2 秒。'}
              inputProps={{ maxLength: 1000 }}
              sx={{
                '& .MuiOutlinedInput-root': { bgcolor: '#0f131a', color: '#f4f7fb' },
                '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.18)' },
              }}
            />
            {cueType === 'voice' && (
              <Tooltip title={recording
                ? '停止朗读录音'
                : '朗读这段台词，AI 将分析你的语速、重音与停顿并生成语音合成指令'}>
                <IconButton
                  aria-label={recording ? '停止朗读录音' : '朗读这段台词'}
                  onClick={() => void handleReadingRecording()}
                  disabled={analyzing || assistLoading}
                  sx={{
                    mt: 0.5,
                    color: recording ? '#ff5c70' : '#2f6df6',
                    border: '1px solid rgba(255,255,255,0.14)',
                    borderRadius: 1,
                  }}
                >
                  {analyzing ? <CircularProgress size={20} /> : recording ? <StopIcon /> : <MicIcon />}
                </IconButton>
              </Tooltip>
            )}
          </Box>

          {cueType === 'voice' && recording && (
            <Alert severity="info">
              正在朗读录音（最长 {MAX_READING_RECORDING_SECONDS} 秒），点击停止后自动分析
            </Alert>
          )}
          {cueType === 'voice' && analyzing && (
            <Alert severity="info" icon={<CircularProgress size={16} />}>AI 正在分析你的朗读特点（含文本一致性校验）</Alert>
          )}

          <Box
            aria-label="提示词示例"
            sx={{
              px: 1.25,
              py: 1,
              borderRadius: 1,
              border: '1px solid rgba(255,255,255,0.08)',
              bgcolor: 'rgba(255,255,255,0.03)',
            }}
          >
            <Typography variant="caption" sx={{ display: 'block', color: '#7d8794', mb: 0.5 }}>
              参考示例
            </Typography>
            {CUE_EXAMPLES[cueType].map((example) => (
              <Typography
                key={example}
                variant="caption"
                sx={{ display: 'block', color: '#7d8794', lineHeight: 1.7 }}
              >
                · {example}
              </Typography>
            ))}
          </Box>

          {(cueType === 'sfx' || cueType === 'bgm') && (
            <AudioPicker
              type={cueType === 'sfx' ? 'sfx' : 'music'}
              value={selectedAsset?.label || description}
              onChange={(value) => {
                setSelectedAsset(null)
                handleDescriptionChange(value)
              }}
              onSelectAsset={(selection) => {
                setSelectedAsset(selection)
                setAssistResult(null)
              }}
              label={cueType === 'sfx' ? '从素材库选择音效' : '从素材库选择配乐'}
              textFieldSx={{
                '& .MuiInputLabel-root': { color: '#9aa4b2' },
                '& .MuiInputLabel-root.Mui-focused': { color: '#9aa4b2' },
                '& .MuiOutlinedInput-root': { bgcolor: '#0f131a', color: '#f4f7fb' },
                '& .MuiOutlinedInput-input::placeholder': { color: '#7d8794', opacity: 1 },
                '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.18)' },
              }}
            />
          )}

          {error && <Alert severity="error">{error}</Alert>}
          {assistResult && (
            <Box sx={{ p: 1.25, border: '1px solid rgba(16,215,226,0.3)', bgcolor: 'rgba(16,215,226,0.06)', borderRadius: 1 }}>
              <Stack spacing={0.75}>
                <Typography variant="caption" sx={{ color: '#9aa4b2' }}>
                  {assistResult.source === 'omni_reading'
                    ? '朗读分析'
                    : `已生成 ${assistResult.source === 'llm' ? '模型' : '规则'} 语义建议`}
                </Typography>
                {assistResult.source === 'omni_reading' && assistResult.performance_summary && (
                  <Typography variant="caption" sx={{ color: '#f4f7fb' }}>
                    朗读特点：{assistResult.performance_summary}
                  </Typography>
                )}
                {assistResult.source === 'omni_reading' && assistResult.spoken_transcript && (
                  <Typography variant="caption" sx={{ color: '#9aa4b2' }}>
                    识别朗读：{assistResult.spoken_transcript}
                  </Typography>
                )}
                {model_capabilities?.model_family && (
                  <Typography variant="caption" sx={{ color: '#9aa4b2' }}>
                    模型能力：{model_capabilities.model_family}
                  </Typography>
                )}
                <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                  {intentEntries.map(([key, value]) => (
                    <Chip key={key} size="small" label={`${key}: ${Array.isArray(value) ? value.join('、') : String(value)}`} />
                  ))}
                </Stack>
                {assistResult.warnings.map((warning) => (
                  <Alert key={warning} severity="warning" icon={<InfoOutlinedIcon />}>{warning}</Alert>
                ))}
              </Stack>
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 2, py: 1.5, borderColor: 'rgba(255,255,255,0.08)' }}>
        <Button onClick={handleClose} startIcon={<CloseIcon />}>取消</Button>
        <Button
          variant="outlined"
          startIcon={assistLoading ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
          disabled={!canAssist || assistLoading || recording || analyzing}
          onClick={() => void handleAssist()}
        >
          智能整理
        </Button>
        <Button
          variant="contained"
          startIcon={<AutoAwesomeIcon />}
          disabled={assistLoading || recording || analyzing || !canApply}
          onClick={handleApply}
          sx={{ bgcolor: color, '&:hover': { bgcolor: color, filter: 'brightness(1.12)' } }}
        >
          应用到片段
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default SegmentCueEditorDialog
