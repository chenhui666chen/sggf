import { useCallback, useEffect, useRef, useState } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import { buildProjectAudioConfigPayload } from './projectAudioConfigUtils'
import type {
  AudioEngineMode,
  AudioFxConfig,
  CharacterVoiceSetting,
  TtsModel,
  VoicePreset,
} from './types'

interface UseAudiobookVoiceConfigAutosaveParams {
  projectId: number | null
  characterVoices: CharacterVoiceSetting[]
  audioFxConfig: AudioFxConfig
  audioEngineMode: AudioEngineMode
  ttsModel: TtsModel
  currentVoicePresets: VoicePreset[]
  setSnackbar: SetSnackbar
}

const AUTOSAVE_DEBOUNCE_MS = 800

/**
 * 用户显式修改角色音色后自动持久化到项目级音频配置，
 * 让再次进入项目时已选音色保持固定，无需重新选择。
 *
 * 只有调用 scheduleVoiceConfigSave 标记后才会保存，
 * 避免项目切换等程序性状态重置误覆盖已保存配置。
 */
export const useAudiobookVoiceConfigAutosave = ({
  projectId,
  characterVoices,
  audioFxConfig,
  audioEngineMode,
  ttsModel,
  currentVoicePresets,
  setSnackbar,
}: UseAudiobookVoiceConfigAutosaveParams) => {
  const { t } = useTranslation()
  const [dirtyCounter, setDirtyCounter] = useState(0)
  const pendingProjectIdRef = useRef<number | null>(null)

  const scheduleVoiceConfigSave = useCallback(() => {
    if (!projectId) return
    pendingProjectIdRef.current = projectId
    setDirtyCounter((count) => count + 1)
  }, [projectId])

  useEffect(() => {
    if (dirtyCounter === 0) return
    if (!projectId || pendingProjectIdRef.current !== projectId) {
      // 项目已切换，放弃未落盘的保存，避免把旧配置写入新项目
      pendingProjectIdRef.current = null
      return
    }

    const timer = window.setTimeout(() => {
      pendingProjectIdRef.current = null
      const payload = buildProjectAudioConfigPayload({
        characterVoices,
        audioFxConfig,
        audioEngineMode,
        ttsModel,
        voicePresets: currentVoicePresets,
      })
      apiClient.updateProjectAudioConfig(projectId, payload, ttsModel).catch(() => {
        setSnackbar({
          open: true,
          message: t('audiobook.useAudiobookVoiceConfigAutosave.autosaveFailed'),
          severity: 'warning',
        })
      })
    }, AUTOSAVE_DEBOUNCE_MS)

    return () => window.clearTimeout(timer)
  }, [
    dirtyCounter,
    projectId,
    characterVoices,
    audioFxConfig,
    audioEngineMode,
    ttsModel,
    currentVoicePresets,
    setSnackbar,
    t,
  ])

  return { scheduleVoiceConfigSave }
}
