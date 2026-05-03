import { useCallback, useEffect, useRef } from 'react'

import { extractApiErrorMessage } from '../../services/api'

interface UseCosyVoiceCloneRecordingParams {
  cloneLoading: boolean
  cloneUploading: boolean
  cloneRecording: boolean
  setCloneRecording: (recording: boolean) => void
  onResetCloneMessages: () => void
  onCloneError: (message: string) => void
  onUploadRecordedCloneAudio: (blob: Blob) => void | Promise<void>
}

export const useCosyVoiceCloneRecording = ({
  cloneLoading,
  cloneUploading,
  cloneRecording,
  setCloneRecording,
  onResetCloneMessages,
  onCloneError,
  onUploadRecordedCloneAudio,
}: UseCosyVoiceCloneRecordingParams) => {
  const cloneRecorderRef = useRef<MediaRecorder | null>(null)
  const cloneStreamRef = useRef<MediaStream | null>(null)
  const cloneChunksRef = useRef<Blob[]>([])

  const stopCloneRecordingStream = useCallback(() => {
    if (cloneStreamRef.current) {
      cloneStreamRef.current.getTracks().forEach((track) => track.stop())
      cloneStreamRef.current = null
    }
  }, [])

  useEffect(() => () => {
    const recorder = cloneRecorderRef.current
    if (recorder) {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.onerror = null
      if (recorder.state !== 'inactive') {
        recorder.stop()
      }
      cloneRecorderRef.current = null
    }
    cloneChunksRef.current = []
    stopCloneRecordingStream()
  }, [stopCloneRecordingStream])

  const handleStartCloneRecording = useCallback(async () => {
    if (cloneLoading || cloneUploading || cloneRecording) return
    if (
      typeof navigator === 'undefined'
      || !navigator.mediaDevices?.getUserMedia
      || typeof MediaRecorder === 'undefined'
    ) {
      onCloneError('当前浏览器不支持录音，请改用上传音频')
      return
    }
    onResetCloneMessages()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      cloneStreamRef.current = stream
      cloneChunksRef.current = []
      const recorder = new MediaRecorder(stream)
      cloneRecorderRef.current = recorder
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          cloneChunksRef.current.push(event.data)
        }
      }
      recorder.onstop = () => {
        const chunks = cloneChunksRef.current
        cloneChunksRef.current = []
        cloneRecorderRef.current = null
        setCloneRecording(false)
        stopCloneRecordingStream()
        if (chunks.length === 0) {
          onCloneError('未获取到录音数据，请重试')
          return
        }
        const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' })
        void onUploadRecordedCloneAudio(blob)
      }
      recorder.onerror = () => {
        cloneRecorderRef.current = null
        setCloneRecording(false)
        stopCloneRecordingStream()
        onCloneError('录音失败，请重试')
      }
      recorder.start()
      setCloneRecording(true)
    } catch (error: unknown) {
      stopCloneRecordingStream()
      setCloneRecording(false)
      const message = await extractApiErrorMessage(error, '无法访问麦克风，请检查权限')
      onCloneError(message)
    }
  }, [
    cloneLoading,
    cloneRecording,
    cloneUploading,
    onCloneError,
    onResetCloneMessages,
    onUploadRecordedCloneAudio,
    setCloneRecording,
    stopCloneRecordingStream,
  ])

  const handleStopCloneRecording = useCallback(() => {
    const recorder = cloneRecorderRef.current
    if (!recorder) return
    if (recorder.state === 'inactive') {
      cloneRecorderRef.current = null
      setCloneRecording(false)
      stopCloneRecordingStream()
      return
    }
    recorder.stop()
  }, [setCloneRecording, stopCloneRecordingStream])

  return {
    handleStartCloneRecording,
    handleStopCloneRecording,
  }
}
