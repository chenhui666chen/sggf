import { useCallback } from 'react'

import { apiClient } from '../../services/api'
import {
  buildInitialProjectVoiceSettings,
  normalizeProjectAudioFxConfig,
  type ProjectCharacterSummary,
} from './projectAudioConfigUtils'
import type {
  AudioEngineMode,
  AudioFxConfig,
  CharacterVoiceSetting,
  TtsModel,
  VoicePreset,
} from './types'

interface UseAudiobookEngineModeSwitchParams {
  projectId: number | null
  ttsModel: TtsModel
  voicePresetsByModel: Partial<Record<TtsModel, VoicePreset[]>>
  setAudioEngineMode: (next: AudioEngineMode) => void
  setCharacterVoicesForCurrentModel: (next: CharacterVoiceSetting[]) => void
  setAudioFxConfig: (next: AudioFxConfig) => void
}

/**
 * 引擎切换重载（GUIDE §2.2）：切换引擎后重新读取目标分支的音色绑定与
 * 创作偏好并刷新角色声音面板；GET audio-config 的顶层 characters 由服务端
 * 按存储模式解析，因此这里显式按目标模式读取 engines 分支。
 */
export const useAudiobookEngineModeSwitch = ({
  projectId,
  ttsModel,
  voicePresetsByModel,
  setAudioEngineMode,
  setCharacterVoicesForCurrentModel,
  setAudioFxConfig,
}: UseAudiobookEngineModeSwitchParams) => {
  const handleEngineModeChange = useCallback(async (nextMode: AudioEngineMode) => {
    setAudioEngineMode(nextMode)
    if (!projectId) {
      return
    }
    try {
      const [charactersRes, audioConfigRes] = await Promise.all([
        apiClient.getCharacters(projectId),
        apiClient.getProjectAudioConfig(projectId, ttsModel),
      ])
      const charactersData: ProjectCharacterSummary[] = Array.isArray(charactersRes.data)
        ? charactersRes.data
        : []
      const projectAudioConfig = audioConfigRes.data
      const nextCharacterVoices = buildInitialProjectVoiceSettings({
        characters: charactersData,
        projectAudioConfig,
        ttsModel,
        voicePresets: voicePresetsByModel[ttsModel] || [],
        engineMode: nextMode,
      })
      setCharacterVoicesForCurrentModel(nextCharacterVoices)
      if (nextMode === 'legacy_stems') {
        const branchFx = projectAudioConfig.engines?.['legacy_stems']?.audio_fx
        setAudioFxConfig(normalizeProjectAudioFxConfig(branchFx ?? projectAudioConfig.audio_fx))
      }
    } catch {
      // 网络错误不阻塞引擎切换，音色绑定保持当前配置，由下次保存回填
    }
  }, [
    projectId,
    setAudioEngineMode,
    setAudioFxConfig,
    setCharacterVoicesForCurrentModel,
    ttsModel,
    voicePresetsByModel,
  ])

  return {
    handleEngineModeChange,
  }
}
