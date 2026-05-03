import { useCallback, useEffect, useMemo, useState } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type {
  CharacterVoiceSetting,
  TtsModel,
  VoiceCatalogMeta,
  VoicePreset,
} from './types'
import {
  FALLBACK_TTS_MODEL_OPTIONS,
  findTtsModelOption,
  getTtsModelLabel,
  mergeTtsModelOptions,
  modelRequiresCustomVoice,
  modelSupportsCustomVoiceWorkbench,
  modelSupportsVoiceTuning,
  normalizeTtsModelOptions,
  type TtsModelOption,
} from './ttsModels'
import { normalizeVoiceCatalogPayload } from './voiceCatalog'

interface UseAudiobookVoiceCatalogParams {
  ttsModel: TtsModel
  characterVoices: CharacterVoiceSetting[]
}

type VoiceCatalogNoticeSeverity = 'success' | 'warning' | 'info'

const sortVoicePresetsForDisplay = (voicePresets: readonly VoicePreset[]): VoicePreset[] => {
  if (voicePresets.length === 0) {
    return []
  }

  return [...voicePresets].sort((a, b) => {
    const catA = a.category || 'general'
    const catB = b.category || 'general'
    if (catA !== catB) {
      return catA.localeCompare(catB, 'zh-CN')
    }
    const labelA = a.label || a.id
    const labelB = b.label || b.id
    return labelA.localeCompare(labelB, 'zh-CN')
  })
}

export const useAudiobookVoiceCatalog = ({
  ttsModel,
  characterVoices,
}: UseAudiobookVoiceCatalogParams) => {
  const [voiceLoading, setVoiceLoading] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [ttsModelOptions, setTtsModelOptions] = useState<readonly TtsModelOption[]>(
    FALLBACK_TTS_MODEL_OPTIONS,
  )
  const [voicePresetsByModel, setVoicePresetsByModel] = useState<Record<TtsModel, VoicePreset[]>>({})
  const [voiceCatalogMetaByModel, setVoiceCatalogMetaByModel] = useState<Record<TtsModel, VoiceCatalogMeta | null>>({})

  const voicePresets = voicePresetsByModel[ttsModel] || []
  const voiceCatalogMeta = voiceCatalogMetaByModel[ttsModel] || null
  const mergedTtsModelOptions = useMemo(
    () => mergeTtsModelOptions(ttsModelOptions, [
      ttsModel,
      ...characterVoices
        .map((voice) => voice.ttsModel)
        .filter((model): model is TtsModel => Boolean(model)),
    ]),
    [characterVoices, ttsModel, ttsModelOptions],
  )
  const currentTtsModelOption = useMemo(
    () => findTtsModelOption(ttsModel, mergedTtsModelOptions),
    [mergedTtsModelOptions, ttsModel],
  )
  const currentModelRequiresCustomVoice = modelRequiresCustomVoice(ttsModel, mergedTtsModelOptions)
  const showCustomVoiceWorkbench = modelSupportsCustomVoiceWorkbench(ttsModel, mergedTtsModelOptions)
  const supportsTtsTuning = modelSupportsVoiceTuning(ttsModel, mergedTtsModelOptions)
  const currentModelCatalogUnavailable = currentTtsModelOption?.catalogStatus === 'unavailable'
  const currentModelRuntimeUnavailable = currentTtsModelOption?.runtimeStatus === 'unavailable'

  const currentVoicePresets = useMemo(
    () => sortVoicePresetsForDisplay(voicePresets),
    [voicePresets],
  )

  const customVoicePresets = useMemo(() => {
    if (!showCustomVoiceWorkbench) {
      return []
    }
    return currentVoicePresets.filter((preset) => preset.category === 'custom')
  }, [currentVoicePresets, showCustomVoiceWorkbench])

  const currentModelHasUsableVoice = useMemo(() => {
    if (currentModelCatalogUnavailable || currentModelRuntimeUnavailable) {
      return false
    }
    if (!currentModelRequiresCustomVoice) {
      return true
    }
    return currentVoicePresets.length > 0 || characterVoices.some((item) => Boolean(item.voiceId))
  }, [
    characterVoices,
    currentModelCatalogUnavailable,
    currentModelRuntimeUnavailable,
    currentModelRequiresCustomVoice,
    currentVoicePresets,
  ])

  const voiceCatalogSummary = useMemo(() => {
    if (!voiceCatalogMeta) {
      return ''
    }

    const modelLabel = currentTtsModelOption?.name || getTtsModelLabel(ttsModel)
    const updatedAt = voiceCatalogMeta.updated_at || '—'
    if (currentModelRequiresCustomVoice) {
      return `${modelLabel}：官方无系统音色，当前展示 ${currentVoicePresets.length} 个可用自定义音色，最近同步 ${updatedAt}。`
    }

    const voiceCount = voiceCatalogMeta.voice_count ?? currentVoicePresets.length
    const capabilityText = currentTtsModelOption?.catalogNote || '适合角色对白、旁白与批量生成。'
    return `${modelLabel}：官方 ${voiceCount} 种音色，最近更新 ${updatedAt}，${capabilityText}`
  }, [
    currentModelRequiresCustomVoice,
    currentTtsModelOption,
    currentVoicePresets.length,
    ttsModel,
    voiceCatalogMeta,
  ])

  const voiceCatalogNotice = useMemo(() => {
    const modelLabel = currentTtsModelOption?.name || getTtsModelLabel(ttsModel)
    if (currentTtsModelOption?.catalogStatus === 'unavailable') {
      return `${modelLabel}：${currentTtsModelOption.catalogError || '音色目录不可用，请检查后端 voice catalog 配置。'}`
    }
    if (currentTtsModelOption?.runtimeStatus === 'unavailable') {
      return `${modelLabel}：${currentTtsModelOption.runtimeError || 'TTS 运行时模型不可用，请检查后端 adapter 注册。'}`
    }
    if (currentTtsModelOption?.source === 'fallback') {
      if (voiceLoading) {
        return `${modelLabel}：正在同步后端模型目录与音色目录。`
      }
      return `${modelLabel}：暂时使用前端内置模型配置，后端模型目录未返回该模型。`
    }
    const note = currentTtsModelOption?.catalogNote
    if (note) {
      return `${modelLabel}：${note}`
    }
    return `${modelLabel}：使用后端模型目录与音色目录配置。`
  }, [currentTtsModelOption, ttsModel, voiceLoading])
  const voiceCatalogNoticeSeverity: VoiceCatalogNoticeSeverity = currentTtsModelOption?.catalogStatus === 'unavailable'
    || currentTtsModelOption?.runtimeStatus === 'unavailable'
    ? 'warning'
    : currentTtsModelOption?.source === 'fallback'
      ? (voiceLoading ? 'info' : 'warning')
    : 'success'

  const refreshVoiceCatalog = useCallback(async (model: TtsModel) => {
    try {
      const res = await apiClient.getTtsVoices(model)
      const catalog = normalizeVoiceCatalogPayload(model, res.data)
      setVoicePresetsByModel((prev) => ({ ...prev, [model]: catalog.voices }))
      setVoiceCatalogMetaByModel((prev) => ({ ...prev, [model]: catalog.meta }))
      if (model === ttsModel) {
        setVoiceError(null)
      }
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, `刷新 ${getTtsModelLabel(model)} 音色库失败`)
      if (model === ttsModel) {
        setVoiceError(message)
      }
      console.error(`刷新 ${model} 音色库失败:`, error)
    }
  }, [ttsModel])

  const fetchVoiceCatalog = useCallback(async () => {
    setVoiceLoading(true)
    try {
      await refreshVoiceCatalog(ttsModel)
    } finally {
      setVoiceLoading(false)
    }
  }, [refreshVoiceCatalog, ttsModel])

  useEffect(() => {
    let cancelled = false

    const loadAllVoiceCatalogs = async () => {
      setVoiceLoading(true)
      try {
        let modelOptions: readonly TtsModelOption[] = FALLBACK_TTS_MODEL_OPTIONS
        try {
          const modelResponse = await apiClient.getTtsModels()
          modelOptions = normalizeTtsModelOptions(modelResponse.data)
        } catch {
          modelOptions = FALLBACK_TTS_MODEL_OPTIONS
        }

        const modelIds = mergeTtsModelOptions(
          modelOptions,
          [
            ttsModel,
            ...characterVoices
              .map((voice) => voice.ttsModel)
              .filter((model): model is TtsModel => Boolean(model)),
          ],
        ).map((option) => option.id)

        const results = await Promise.allSettled(
          modelIds.map(async (model) => {
            const res = await apiClient.getTtsVoices(model)
            return {
              model,
              catalog: normalizeVoiceCatalogPayload(model, res.data),
            }
          }),
        )

        if (cancelled) {
          return
        }

        const loadedCatalogs = results
          .filter((result): result is PromiseFulfilledResult<{
            model: TtsModel
            catalog: ReturnType<typeof normalizeVoiceCatalogPayload>
          }> => result.status === 'fulfilled')
          .map((result) => result.value)
        const failedModels = results
          .map((result, index) => ({ result, model: modelIds[index] }))
          .filter((item): item is {
            result: PromiseRejectedResult
            model: TtsModel
          } => item.result.status === 'rejected')
          .map((item) => item.model)

        if (loadedCatalogs.length === 0) {
          const firstFailure = results.find((result): result is PromiseRejectedResult =>
            result.status === 'rejected',
          )
          throw firstFailure?.reason || new Error('加载音色库失败')
        }

        const newPresetsByModel: Record<TtsModel, VoicePreset[]> = {}
        const newMetaByModel: Record<TtsModel, VoiceCatalogMeta | null> = {}

        for (const { catalog } of loadedCatalogs) {
          newPresetsByModel[catalog.model] = catalog.voices
          newMetaByModel[catalog.model] = catalog.meta
        }

        setTtsModelOptions(mergeTtsModelOptions(modelOptions, modelIds))
        setVoicePresetsByModel(newPresetsByModel)
        setVoiceCatalogMetaByModel(newMetaByModel)
        if (failedModels.length === 0) {
          setVoiceError(null)
        } else if (failedModels.includes(ttsModel)) {
          setVoiceError(`加载 ${getTtsModelLabel(ttsModel)} 音色库失败，请重新同步。`)
        } else {
          setVoiceError(`部分音色库加载失败：${failedModels.map(getTtsModelLabel).join('、')}。`)
        }
      } catch (error: unknown) {
        if (!cancelled) {
          const message = await extractApiErrorMessage(error, '加载音色库失败')
          setVoiceError(message)
        }
      } finally {
        if (!cancelled) {
          setVoiceLoading(false)
        }
      }
    }

    void loadAllVoiceCatalogs()

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (voiceCatalogMetaByModel[ttsModel] || voiceLoading) {
      return
    }
    void refreshVoiceCatalog(ttsModel)
  }, [refreshVoiceCatalog, ttsModel, voiceCatalogMetaByModel, voiceLoading])

  return {
    ttsModelOptions: mergedTtsModelOptions,
    currentTtsModelOption,
    voicePresets,
    voiceCatalogMeta,
    voiceLoading,
    voiceError,
    voicePresetsByModel,
    voiceCatalogMetaByModel,
    currentVoicePresets,
    customVoicePresets,
    currentModelRequiresCustomVoice,
    currentModelHasUsableVoice,
    currentModelCatalogUnavailable,
    currentModelRuntimeUnavailable,
    showCustomVoiceWorkbench,
    supportsTtsTuning,
    voiceCatalogSummary,
    voiceCatalogNotice,
    voiceCatalogNoticeSeverity,
    refreshVoiceCatalog,
    fetchVoiceCatalog,
  }
}
