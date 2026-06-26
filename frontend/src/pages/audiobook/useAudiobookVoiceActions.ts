import { useCallback, useState, type ChangeEvent, type SetStateAction } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type {
  CharacterVoiceSetting,
  TtsModel,
  VoicePreset,
} from './types'
import type { SetSnackbar } from './hookTypes'
import {
  createRecordedCloneAudioFile,
  uploadCosyVoiceCloneSampleFile,
} from './voiceCloneAudioUtils'
import { DEFAULT_DESIGN_PREVIEW_TEXT } from './pageSessionUtils'
import { applyProjectVoiceAssignments } from './projectAudioConfigUtils'
import { useCosyVoiceCloneRecording } from './useCosyVoiceCloneRecording'

const COSYVOICE_PREVIEW_MIME_BY_FORMAT: Record<string, string> = {
  mp3: 'audio/mpeg',
  pcm: 'audio/pcm',
  wav: 'audio/wav',
}

export const normalizeCosyVoicePreviewAudioUrl = (
  value: unknown,
  fallbackFormat = 'wav',
): string => {
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text) return ''
  if (/^(https?:|blob:|data:audio\/)/i.test(text)) return text

  const compactBase64 = text.replace(/\s+/g, '')
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(compactBase64)) return text

  const mimeType = COSYVOICE_PREVIEW_MIME_BY_FORMAT[fallbackFormat] || COSYVOICE_PREVIEW_MIME_BY_FORMAT.wav
  return `data:${mimeType};base64,${compactBase64}`
}

interface UseAudiobookVoiceActionsParams {
  selectedProjectId: number | null
  routeProjectId?: number | null
  ttsModel: TtsModel
  characterVoices: CharacterVoiceSetting[]
  setCharacterVoicesForCurrentModel: (next: CharacterVoiceSetting[]) => void
  updateCharacterVoicesForCurrentModel: (
    updater: (prev: CharacterVoiceSetting[]) => CharacterVoiceSetting[],
  ) => void
  refreshVoiceCatalog: (model: TtsModel) => Promise<void>
  playExternalUrl: (url: string) => Promise<unknown>
  playManagedBlob: (blob: Blob) => Promise<unknown>
  setSnackbar: SetSnackbar
}

export const useAudiobookVoiceActions = ({
  selectedProjectId,
  routeProjectId,
  ttsModel,
  characterVoices,
  setCharacterVoicesForCurrentModel,
  updateCharacterVoicesForCurrentModel,
  refreshVoiceCatalog,
  playExternalUrl,
  playManagedBlob,
  setSnackbar,
}: UseAudiobookVoiceActionsParams) => {
  const [cloneName, setCloneName] = useState('')
  const [cloneUrl, setCloneUrl] = useState('')
  const [cloneLoading, setCloneLoading] = useState(false)
  const [cloneUploading, setCloneUploading] = useState(false)
  const [cloneRecording, setCloneRecording] = useState(false)
  const [cloneRecordDialogOpen, setCloneRecordDialogOpen] = useState(false)
  const [cloneDeletingId, setCloneDeletingId] = useState<string | null>(null)
  const [cloneError, setCloneError] = useState<string | null>(null)
  const [cloneSuccess, setCloneSuccess] = useState<string | null>(null)
  const [designName, setDesignName] = useState('')
  const [designPrompt, setDesignPrompt] = useState('')
  const [designPreviewText, setDesignPreviewText] = useState(DEFAULT_DESIGN_PREVIEW_TEXT)
  const [designPreviewAudioUrl, setDesignPreviewAudioUrl] = useState('')
  const [designPreviewVoiceId, setDesignPreviewVoiceId] = useState('')
  const [designLoading, setDesignLoading] = useState(false)
  const [designError, setDesignError] = useState<string | null>(null)
  const [designSuccess, setDesignSuccess] = useState<string | null>(null)
  const [customVoicePreviewingId, setCustomVoicePreviewingId] = useState<string | null>(null)
  const [autoAssigningVoices, setAutoAssigningVoices] = useState(false)

  const clearVoiceCreationMessages = useCallback(() => {
    setCloneError(null)
    setCloneSuccess(null)
    setDesignError(null)
    setDesignSuccess(null)
  }, [])

  const clearCloneMessages = useCallback(() => {
    setCloneError(null)
    setCloneSuccess(null)
  }, [])

  const updateDesignName = useCallback((value: SetStateAction<string>) => {
    setDesignPreviewAudioUrl('')
    setDesignPreviewVoiceId('')
    setDesignName(value)
  }, [])

  const updateDesignPrompt = useCallback((value: SetStateAction<string>) => {
    setDesignPreviewAudioUrl('')
    setDesignPreviewVoiceId('')
    setDesignPrompt(value)
  }, [])

  const updateDesignPreviewText = useCallback((value: SetStateAction<string>) => {
    setDesignPreviewAudioUrl('')
    setDesignPreviewVoiceId('')
    setDesignPreviewText(value)
  }, [])

  const handleCreateCloneVoice = useCallback(async () => {
    setCloneLoading(true)
    clearVoiceCreationMessages()
    try {
      const name = cloneName.trim()
      const url = cloneUrl.trim()
      const res = await apiClient.createCosyVoiceV3PlusClone({ name, url })
      const voiceId = (res.data?.voice_id as string) || ''
      setCloneSuccess(voiceId ? `已提交复刻任务：${voiceId}` : '已提交复刻任务')
      setCloneName('')
      setCloneUrl('')
      await refreshVoiceCatalog('cosyvoice-v3.5-plus')
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '创建复刻音色失败')
      setCloneError(message)
    } finally {
      setCloneLoading(false)
    }
  }, [clearVoiceCreationMessages, cloneName, cloneUrl, refreshVoiceCatalog])

  const handleCreateDesignVoice = useCallback(async () => {
    setDesignLoading(true)
    clearVoiceCreationMessages()
    try {
      const name = designName.trim()
      const voicePrompt = designPrompt.trim()
      const previewText = designPreviewText.trim() || DEFAULT_DESIGN_PREVIEW_TEXT
      const res = await apiClient.createCosyVoiceV3PlusDesign({
        name,
        voice_prompt: voicePrompt,
        preview_text: previewText,
      })
      const voiceId = (res.data?.voice_id as string) || ''
      const previewAudio = normalizeCosyVoicePreviewAudioUrl(res.data?.preview_audio)
      setDesignPreviewVoiceId(voiceId)
      setDesignPreviewAudioUrl(previewAudio)
      setDesignSuccess(
        previewAudio || voiceId
          ? (voiceId ? `已提交声音设计任务：${voiceId}，可直接试听。` : '已提交声音设计任务，可直接试听。')
          : (voiceId ? `已提交声音设计任务：${voiceId}` : '已提交声音设计任务'),
      )
      await refreshVoiceCatalog('cosyvoice-v3.5-plus')
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '创建设计音色失败')
      setDesignError(message)
    } finally {
      setDesignLoading(false)
    }
  }, [clearVoiceCreationMessages, designName, designPreviewText, designPrompt, refreshVoiceCatalog])

  const handlePreviewDesignVoice = useCallback(async () => {
    const previewAudio = designPreviewAudioUrl.trim()
    const voiceId = designPreviewVoiceId.trim()
    if (!previewAudio && !voiceId) return
    try {
      if (previewAudio) {
        await playExternalUrl(previewAudio)
        return
      }
      const response = await apiClient.previewTTSCached({
        text: DEFAULT_DESIGN_PREVIEW_TEXT,
        voice_id: voiceId,
        volume: 50,
        speed: 1.0,
        pitch: 50,
        model: 'cosyvoice-v3.5-plus',
      })
      if (response.audioUrl) {
        await playExternalUrl(response.audioUrl)
      } else if (response.blob) {
        await playManagedBlob(response.blob)
      }
    } catch (error: unknown) {
      setDesignError(await extractApiErrorMessage(error, '试听设计音色失败'))
    }
  }, [designPreviewAudioUrl, designPreviewVoiceId, playExternalUrl, playManagedBlob])

  const handlePreviewCustomVoice = useCallback(async (
    voice: VoicePreset,
    model: TtsModel = 'cosyvoice-v3.5-plus',
  ) => {
    const voiceId = (voice.speaker || voice.id || '').trim()
    if (!voiceId) return
    try {
      setCustomVoicePreviewingId(voice.id)
      const isMimoModel = model.startsWith('mimo-v2.5-tts-')
      const isStepAudioModel = model === 'stepaudio-2.5-tts'
      const response = await apiClient.previewTTSCached({
        text: DEFAULT_DESIGN_PREVIEW_TEXT,
        voice_id: voiceId,
        volume: voice.default_params?.volume ?? 50,
        speed: voice.default_params?.speed ?? 1.0,
        pitch: voice.default_params?.pitch ?? 50,
        model,
        mimo_voice_asset_id: isMimoModel ? voice.id : undefined,
        stepaudio_voice_asset_id: isStepAudioModel ? voice.id : undefined,
      })
      if (response.audioUrl) {
        await playExternalUrl(response.audioUrl)
      } else if (response.blob) {
        await playManagedBlob(response.blob)
      }
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '自定义音色试听失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setCustomVoicePreviewingId(null)
    }
  }, [playExternalUrl, playManagedBlob, setSnackbar])

  const handleDeleteCustomVoice = useCallback(async (voiceId: string, label?: string) => {
    if (!voiceId || cloneDeletingId) return
    const displayName = label || voiceId
    setCloneDeletingId(voiceId)
    clearVoiceCreationMessages()
    try {
      await apiClient.deleteCosyVoiceV3PlusClone(voiceId)
      updateCharacterVoicesForCurrentModel((prev) =>
        prev.map((item) => (item.voiceId === voiceId ? { ...item, voiceId: '' } : item)),
      )
      setCloneSuccess(`已删除自定义音色：${displayName}`)
      await refreshVoiceCatalog('cosyvoice-v3.5-plus')
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '删除自定义音色失败')
      setCloneError(message)
    } finally {
      setCloneDeletingId(null)
    }
  }, [
    clearVoiceCreationMessages,
    cloneDeletingId,
    refreshVoiceCatalog,
    updateCharacterVoicesForCurrentModel,
  ])

  const handleUploadCloneAudio = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setCloneUploading(true)
    clearCloneMessages()
    try {
      const url = await uploadCosyVoiceCloneSampleFile(file)
      setCloneUrl(url)
      setCloneSuccess('已上传音频并生成临时URL（48小时有效）')
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '上传音频失败')
      setCloneError(message)
    } finally {
      setCloneUploading(false)
    }
  }, [clearCloneMessages])

  const uploadRecordedCloneAudio = useCallback(async (blob: Blob) => {
    setCloneRecordDialogOpen(false)
    setCloneUploading(true)
    clearCloneMessages()
    try {
      const file = createRecordedCloneAudioFile(blob)
      const url = await uploadCosyVoiceCloneSampleFile(file)
      setCloneUrl(url)
      setCloneSuccess('录音已上传并生成临时URL（48小时有效）')
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '上传录音失败')
      setCloneError(message)
    } finally {
      setCloneUploading(false)
    }
  }, [clearCloneMessages])

  const {
    handleStartCloneRecording,
    handleStopCloneRecording,
  } = useCosyVoiceCloneRecording({
    cloneLoading,
    cloneUploading,
    cloneRecording,
    setCloneRecording,
    onResetCloneMessages: clearCloneMessages,
    onCloneError: setCloneError,
    onUploadRecordedCloneAudio: uploadRecordedCloneAudio,
  })

  const handleOpenCloneRecordDialog = useCallback(() => {
    setCloneRecordDialogOpen(true)
  }, [])

  const handleCloseCloneRecordDialog = useCallback(() => {
    if (cloneRecording) return
    setCloneRecordDialogOpen(false)
  }, [cloneRecording])

  const handleAutoAssignVoices = useCallback(async () => {
    const targetProjectId = selectedProjectId ?? routeProjectId
    if (!targetProjectId) {
      setSnackbar({
        open: true,
        message: '请先选择项目后再进行智能推荐声线。',
        severity: 'warning',
      })
      return
    }

    try {
      setAutoAssigningVoices(true)
      const res = await apiClient.autoAssignProjectAudioVoices(targetProjectId, ttsModel)
      const configData = res.data || { characters: [] }

      const assignmentResult = applyProjectVoiceAssignments({
        characterVoices,
        savedCharacters: configData.characters || [],
        ttsModel,
      })
      setCharacterVoicesForCurrentModel(assignmentResult.characterVoices)

      if (assignmentResult.assignedCount > 0) {
        setSnackbar({
          open: true,
          message: `已为 ${assignmentResult.assignedCount} 个角色智能推荐声线，请检查推荐结果，如需调整可手动修改。`,
          severity: 'success',
        })
      } else {
        setSnackbar({
          open: true,
          message: '当前项目还没有角色档案，请先在「项目详情 → 人物设定」中创建角色。',
          severity: 'warning',
        })
      }
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '自动推荐声线失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setAutoAssigningVoices(false)
    }
  }, [
    characterVoices,
    routeProjectId,
    selectedProjectId,
    setCharacterVoicesForCurrentModel,
    setSnackbar,
    ttsModel,
  ])

  return {
    cloneName,
    setCloneName,
    cloneUrl,
    setCloneUrl,
    cloneLoading,
    cloneUploading,
    cloneRecording,
    cloneRecordDialogOpen,
    setCloneRecordDialogOpen,
    cloneDeletingId,
    cloneError,
    cloneSuccess,
    designName,
    setDesignName: updateDesignName,
    designPrompt,
    setDesignPrompt: updateDesignPrompt,
    designPreviewText,
    setDesignPreviewText: updateDesignPreviewText,
    designPreviewAudioUrl,
    designPreviewVoiceId,
    designLoading,
    designError,
    designSuccess,
    customVoicePreviewingId,
    autoAssigningVoices,
    handleCreateCloneVoice,
    handleCreateDesignVoice,
    handlePreviewDesignVoice,
    handlePreviewCustomVoice,
    handleDeleteCustomVoice,
    handleUploadCloneAudio,
    handleStartCloneRecording,
    handleStopCloneRecording,
    handleOpenCloneRecordDialog,
    handleCloseCloneRecordDialog,
    handleAutoAssignVoices,
  }
}
