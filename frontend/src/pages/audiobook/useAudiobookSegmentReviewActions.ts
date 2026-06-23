import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type {
  AudiobookEditorSessionState,
  PendingSegmentRegenerationMap,
  PreviewType,
  ScriptEditorStateData,
  ScriptSegment,
  TtsModel,
} from './types'

type SegmentReviews = NonNullable<AudiobookEditorSessionState['segmentReviews']>

interface UseAudiobookSegmentReviewActionsParams {
  audiobookProjectId?: number | null
  chapterId?: number | null
  ttsModel: TtsModel
  setSnackbar: SetSnackbar
  setScriptEditorData: Dispatch<SetStateAction<ScriptEditorStateData | null>>
}

interface SegmentVoiceRecordingContext {
  index: number
  segment: ScriptSegment
}

const PREVIEW_TYPE_LABELS: Record<PreviewType, string> = {
  voice: '人声',
  sfx: '音效',
  bgm: '配乐',
  mix: '融合',
}

const getSegmentVoiceRecordingExtension = (mimeType: string) => {
  const normalized = mimeType.toLowerCase()
  if (normalized.includes('ogg')) return 'ogg'
  if (normalized.includes('wav')) return 'wav'
  if (normalized.includes('mpeg') || normalized.includes('mp3')) return 'mp3'
  return 'webm'
}

const createSegmentVoiceRecordingFile = (blob: Blob, now = Date.now()) => {
  const extension = getSegmentVoiceRecordingExtension(blob.type || 'audio/webm')
  return new File([blob], `segment_voice_${now}.${extension}`, { type: blob.type || 'audio/webm' })
}

export const useAudiobookSegmentReviewActions = ({
  audiobookProjectId,
  chapterId,
  ttsModel,
  setSnackbar,
  setScriptEditorData,
}: UseAudiobookSegmentReviewActionsParams) => {
  const [reviewMode, setReviewMode] = useState(false)
  const [segmentReviews, setSegmentReviews] = useState<SegmentReviews>({})
  const [regeneratingSegments, setRegeneratingSegments] = useState<Set<number>>(() => new Set())
  const [pendingSegmentRegenerations, setPendingSegmentRegenerations] = useState<PendingSegmentRegenerationMap>({})
  const [recordingSegmentIndex, setRecordingSegmentIndex] = useState<number | null>(null)
  const segmentVoiceRecorderRef = useRef<MediaRecorder | null>(null)
  const segmentVoiceStreamRef = useRef<MediaStream | null>(null)
  const segmentVoiceChunksRef = useRef<Blob[]>([])
  const segmentVoiceContextRef = useRef<SegmentVoiceRecordingContext | null>(null)

  const stopSegmentVoiceRecordingStream = useCallback(() => {
    segmentVoiceStreamRef.current?.getTracks().forEach((track) => track.stop())
    segmentVoiceStreamRef.current = null
  }, [])

  const abortSegmentVoiceRecording = useCallback(() => {
    const recorder = segmentVoiceRecorderRef.current
    if (recorder) {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.onerror = null
      if (recorder.state !== 'inactive') {
        recorder.stop()
      }
    }
    segmentVoiceRecorderRef.current = null
    segmentVoiceChunksRef.current = []
    segmentVoiceContextRef.current = null
    setRecordingSegmentIndex(null)
    stopSegmentVoiceRecordingStream()
  }, [stopSegmentVoiceRecordingStream])

  useEffect(() => () => {
    abortSegmentVoiceRecording()
  }, [abortSegmentVoiceRecording])

  const resetSegmentReviewState = useCallback(() => {
    abortSegmentVoiceRecording()
    setReviewMode(false)
    setSegmentReviews({})
    setRegeneratingSegments(new Set())
    setPendingSegmentRegenerations({})
  }, [abortSegmentVoiceRecording])

  const handleToggleReviewMode = useCallback(() => {
    setReviewMode((prev) => !prev)
  }, [])

  const handleReviewSegment = useCallback(async (index: number, score: number) => {
    if (!audiobookProjectId || !chapterId) return
    try {
      await apiClient.reviewSegment(audiobookProjectId, chapterId, index, { quality_score: score })
      setSegmentReviews((prev) => ({ ...prev, [index]: { quality_score: score } }))
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '保存评分失败')
      setSnackbar({ open: true, message, severity: 'error' })
    }
  }, [audiobookProjectId, chapterId, setSnackbar])

  const handleRegenerateSegment = useCallback(async (
    index: number,
    segment: ScriptSegment,
    previewType: PreviewType,
  ) => {
    if (!audiobookProjectId || !chapterId) return
    setRegeneratingSegments((prev) => new Set([...prev, index]))
    try {
      const voiceParams = segment.voice_params || {}
      const candidateResponse = await apiClient.generateSegmentRegenerationCandidate(audiobookProjectId, chapterId, index, {
        reason: `${PREVIEW_TYPE_LABELS[previewType]}候选重新生成`,
        tts_model: ttsModel,
        segment,
        preview_type: previewType,
        voice_id: previewType === 'voice' || previewType === 'mix' ? voiceParams.speaker ?? undefined : undefined,
        emotion: previewType === 'voice' || previewType === 'mix' ? voiceParams.emotion ?? undefined : undefined,
      })
      const candidateAudioPath = candidateResponse.data?.candidate_audio_path
      if (!candidateAudioPath) {
        throw new Error('候选音频路径缺失')
      }

      setPendingSegmentRegenerations((prev) => ({
        ...prev,
        [index]: {
          ...(prev[index] || {}),
          [previewType]: {
            candidateAudioPath,
            previewType: candidateResponse.data?.preview_type || previewType,
            segment: {
              ...segment,
              ...(candidateResponse.data?.segment || {}),
            },
            generatedAt: new Date().toISOString(),
          },
        },
      }))
      setSnackbar({
        open: true,
        message: `片段 #${index + 1} 已生成${PREVIEW_TYPE_LABELS[previewType]}候选版本，可试听后保存或取消`,
        severity: 'success',
      })
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '请稍后重试')
      setSnackbar({ open: true, message: `${PREVIEW_TYPE_LABELS[previewType]}重新生成失败: ${message}`, severity: 'error' })
    } finally {
      setRegeneratingSegments((prev) => {
        const next = new Set(prev)
        next.delete(index)
        return next
      })
    }
  }, [audiobookProjectId, chapterId, setSnackbar, ttsModel])

  const uploadSegmentVoiceRecording = useCallback(async (
    index: number,
    segment: ScriptSegment,
    blob: Blob,
  ) => {
    if (!audiobookProjectId || !chapterId) return
    const voicePreviewType: PreviewType = 'voice'
    setRegeneratingSegments((prev) => new Set([...prev, index]))
    try {
      const file = createSegmentVoiceRecordingFile(blob)
      const candidateResponse = await apiClient.uploadSegmentVoiceRecordingCandidate(
        audiobookProjectId,
        chapterId,
        index,
        file,
        {
          reason: '真人配音',
          segment,
        },
      )
      const candidateAudioPath = candidateResponse.data?.candidate_audio_path
      if (!candidateAudioPath) {
        throw new Error('配音候选音频路径缺失')
      }

      setPendingSegmentRegenerations((prev) => ({
        ...prev,
        [index]: {
          ...(prev[index] || {}),
          [voicePreviewType]: {
            candidateAudioPath,
            previewType: candidateResponse.data?.preview_type || 'voice',
            segment: {
              ...segment,
              ...(candidateResponse.data?.segment || {}),
            },
            generatedAt: new Date().toISOString(),
          },
        },
      }))
      setSnackbar({
        open: true,
        message: `片段 #${index + 1} 真人配音已生成候选，可试听后保存或取消`,
        severity: 'success',
      })
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '上传配音失败')
      setSnackbar({ open: true, message, severity: 'error' })
    } finally {
      setRegeneratingSegments((prev) => {
        const next = new Set(prev)
        next.delete(index)
        return next
      })
    }
  }, [audiobookProjectId, chapterId, setSnackbar])

  const handleStartSegmentVoiceRecording = useCallback(async (
    index: number,
    segment: ScriptSegment,
  ) => {
    if (!audiobookProjectId || !chapterId || recordingSegmentIndex !== null || regeneratingSegments.has(index)) return
    if (
      typeof navigator === 'undefined'
      || !navigator.mediaDevices?.getUserMedia
      || typeof MediaRecorder === 'undefined'
    ) {
      setSnackbar({ open: true, message: '当前浏览器不支持录音，请换用支持麦克风录制的浏览器', severity: 'error' })
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      segmentVoiceStreamRef.current = stream
      segmentVoiceChunksRef.current = []
      segmentVoiceContextRef.current = { index, segment }

      const recorder = new MediaRecorder(stream)
      segmentVoiceRecorderRef.current = recorder
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          segmentVoiceChunksRef.current.push(event.data)
        }
      }
      recorder.onstop = () => {
        const chunks = segmentVoiceChunksRef.current
        const context = segmentVoiceContextRef.current
        segmentVoiceChunksRef.current = []
        segmentVoiceContextRef.current = null
        segmentVoiceRecorderRef.current = null
        setRecordingSegmentIndex(null)
        stopSegmentVoiceRecordingStream()

        if (!context) return
        if (chunks.length === 0) {
          setSnackbar({ open: true, message: '未获取到配音录音数据，请重试', severity: 'error' })
          return
        }
        const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' })
        void uploadSegmentVoiceRecording(context.index, context.segment, blob)
      }
      recorder.onerror = () => {
        segmentVoiceRecorderRef.current = null
        segmentVoiceChunksRef.current = []
        segmentVoiceContextRef.current = null
        setRecordingSegmentIndex(null)
        stopSegmentVoiceRecordingStream()
        setSnackbar({ open: true, message: '配音录制失败，请重试', severity: 'error' })
      }
      recorder.start()
      setRecordingSegmentIndex(index)
      setSnackbar({ open: true, message: `片段 #${index + 1} 正在配音录制，完成后点击结束配音`, severity: 'info' })
    } catch (error: unknown) {
      abortSegmentVoiceRecording()
      const message = await extractApiErrorMessage(error, '无法访问麦克风，请检查浏览器权限')
      setSnackbar({ open: true, message, severity: 'error' })
    }
  }, [
    abortSegmentVoiceRecording,
    audiobookProjectId,
    chapterId,
    recordingSegmentIndex,
    regeneratingSegments,
    setSnackbar,
    stopSegmentVoiceRecordingStream,
    uploadSegmentVoiceRecording,
  ])

  const handleStopSegmentVoiceRecording = useCallback(() => {
    const recorder = segmentVoiceRecorderRef.current
    if (!recorder) return
    if (recorder.state === 'inactive') {
      abortSegmentVoiceRecording()
      return
    }
    recorder.stop()
  }, [abortSegmentVoiceRecording])

  const handleApplySegmentRegenerationCandidate = useCallback(async (index: number, previewType: PreviewType) => {
    if (!audiobookProjectId || !chapterId) return
    const pending = pendingSegmentRegenerations[index]?.[previewType]
    if (!pending) return

    setRegeneratingSegments((prev) => new Set([...prev, index]))
    try {
      const applyResponse = await apiClient.applySegmentRegenerationCandidate(audiobookProjectId, chapterId, index, {
        candidate_audio_path: pending.candidateAudioPath,
        reason: `应用${PREVIEW_TYPE_LABELS[previewType]}候选版本`,
        segment: pending.segment,
        preview_type: previewType,
      })
      const appliedSegment = applyResponse.data?.segment
      if (appliedSegment) {
        setScriptEditorData((prev) => {
          if (!prev) return prev
          const nextSegments = [...prev.scriptSegments]
          nextSegments[index] = {
            ...nextSegments[index],
            ...appliedSegment,
          }
          return { ...prev, scriptSegments: nextSegments }
        })
      }
      setPendingSegmentRegenerations((prev) => {
        const nextForSegment = { ...(prev[index] || {}) }
        delete nextForSegment[previewType]
        const next = { ...prev }
        if (Object.keys(nextForSegment).length > 0) {
          next[index] = nextForSegment
        } else {
          delete next[index]
        }
        return next
      })
      setSnackbar({
        open: true,
        message: `片段 #${index + 1} ${PREVIEW_TYPE_LABELS[previewType]}候选版本已保存`,
        severity: 'success',
      })
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '请稍后重试')
      setSnackbar({ open: true, message: `保存${PREVIEW_TYPE_LABELS[previewType]}候选版本失败: ${message}`, severity: 'error' })
    } finally {
      setRegeneratingSegments((prev) => {
        const next = new Set(prev)
        next.delete(index)
        return next
      })
    }
  }, [audiobookProjectId, chapterId, pendingSegmentRegenerations, setScriptEditorData, setSnackbar])

  const handleDiscardSegmentRegenerationCandidate = useCallback((index: number, previewType: PreviewType) => {
    setPendingSegmentRegenerations((prev) => {
      if (!prev[index]?.[previewType]) return prev
      const nextForSegment = { ...(prev[index] || {}) }
      delete nextForSegment[previewType]
      const next = { ...prev }
      if (Object.keys(nextForSegment).length > 0) {
        next[index] = nextForSegment
      } else {
        delete next[index]
      }
      return next
    })
    setSnackbar({
      open: true,
      message: `片段 #${index + 1} ${PREVIEW_TYPE_LABELS[previewType]}候选版本已取消`,
      severity: 'info',
    })
  }, [setSnackbar])

  return {
    reviewMode,
    setReviewMode,
    segmentReviews,
    setSegmentReviews,
    regeneratingSegments,
    recordingSegmentIndex,
    pendingSegmentRegenerations,
    resetSegmentReviewState,
    handleToggleReviewMode,
    handleReviewSegment,
    handleRegenerateSegment,
    handleStartSegmentVoiceRecording,
    handleStopSegmentVoiceRecording,
    handleApplySegmentRegenerationCandidate,
    handleDiscardSegmentRegenerationCandidate,
  }
}
