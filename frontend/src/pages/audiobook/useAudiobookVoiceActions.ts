import { useCallback, useState, type ChangeEvent } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type {
  CharacterVoiceSetting,
  TtsModel,
} from './types'
import type { SetSnackbar } from './hookTypes'
import {
  createRecordedCloneAudioFile,
  uploadCosyVoiceCloneSampleFile,
} from './cosyVoiceCloneUploadUtils'
import { DEFAULT_DESIGN_PREVIEW_TEXT } from './pageSessionUtils'
import { applyProjectVoiceAssignments } from './projectAudioConfigUtils'
import { useCosyVoiceCloneRecording } from './useCosyVoiceCloneRecording'

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
  const [designLoading, setDesignLoading] = useState(false)
  const [designError, setDesignError] = useState<string | null>(null)
  const [designSuccess, setDesignSuccess] = useState<string | null>(null)
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
      const previewText = designPreviewText.trim()
      const res = await apiClient.createCosyVoiceV3PlusDesign({
        name,
        voice_prompt: voicePrompt,
        preview_text: previewText,
      })
      const voiceId = (res.data?.voice_id as string) || ''
      setDesignSuccess(voiceId ? `已提交声音设计任务：${voiceId}` : '已提交声音设计任务')
      setDesignName('')
      setDesignPrompt('')
      setDesignPreviewText(DEFAULT_DESIGN_PREVIEW_TEXT)
      await refreshVoiceCatalog('cosyvoice-v3.5-plus')
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '创建设计音色失败')
      setDesignError(message)
    } finally {
      setDesignLoading(false)
    }
  }, [clearVoiceCreationMessages, designName, designPreviewText, designPrompt, refreshVoiceCatalog])

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
    setDesignName,
    designPrompt,
    setDesignPrompt,
    designPreviewText,
    setDesignPreviewText,
    designLoading,
    designError,
    designSuccess,
    autoAssigningVoices,
    handleCreateCloneVoice,
    handleCreateDesignVoice,
    handleDeleteCustomVoice,
    handleUploadCloneAudio,
    handleStartCloneRecording,
    handleStopCloneRecording,
    handleOpenCloneRecordDialog,
    handleCloseCloneRecordDialog,
    handleAutoAssignVoices,
  }
}
