import { useCallback, useEffect, useMemo, useState } from 'react'

import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
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
  const currentModelCatalogUnavailable = currentTtsModelOption?.catalogStatus === 'unavailable'
  const currentModelRuntimeUnavailable = currentTtsModelOption?.runtimeStatus === 'unavailable'

  const currentVoicePresets = useMemo(
    () => sortVoicePresetsForDisplay(voicePresets),
    [voicePresets],
  )

  const customVoicePresets = useMemo(() => {
    return currentVoicePresets.filter((preset) => preset.category === 'custom')
  }, [currentVoicePresets])

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
      return t('audiobook.useAudiobookVoiceCatalog.summaryNoSystemVoices', { model: modelLabel, total: currentVoicePresets.length, updatedAt })
    }

    const voiceCount = voiceCatalogMeta.voice_count ?? currentVoicePresets.length
    const capabilityText = currentTtsModelOption?.catalogNote || t('audiobook.useAudiobookVoiceCatalog.capabilityFallback')
    return t('audiobook.useAudiobookVoiceCatalog.summaryWithCatalog', { model: modelLabel, total: voiceCount, updatedAt, capability: capabilityText })
  }, [
    currentModelRequiresCustomVoice,
    currentTtsModelOption,
    currentVoicePresets.length,
    t,
    ttsModel,
    voiceCatalogMeta,
  ])

  const voiceCatalogNotice = useMemo(() => {
    const modelLabel = currentTtsModelOption?.name || getTtsModelLabel(ttsModel)
    if (currentTtsModelOption?.catalogStatus === 'unavailable') {
      return t('audiobook.useAudiobookVoiceCatalog.noticeWithError', { model: modelLabel, error: currentTtsModelOption.catalogError || t('audiobook.useAudiobookVoiceCatalog.catalogUnavailable') })
    }
    if (currentTtsModelOption?.runtimeStatus === 'unavailable') {
      return t('audiobook.useAudiobookVoiceCatalog.noticeWithError', { model: modelLabel, error: currentTtsModelOption.runtimeError || t('audiobook.useAudiobookVoiceCatalog.runtimeUnavailable') })
    }
    if (currentTtsModelOption?.source === 'fallback') {
      if (voiceLoading) {
        return t('audiobook.useAudiobookVoiceCatalog.syncingNotice', { model: modelLabel })
      }
      return t('audiobook.useAudiobookVoiceCatalog.fallbackModelNotice', { model: modelLabel })
    }
    const note = currentTtsModelOption?.catalogNote
    if (note) {
      return `${modelLabel}：${note}`
    }
    return t('audiobook.useAudiobookVoiceCatalog.backendConfigNotice', { model: modelLabel })
  }, [currentTtsModelOption, t, ttsModel, voiceLoading])
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
      const message = await extractApiErrorMessage(error, t('audiobook.useAudiobookVoiceCatalog.refreshFailed', { model: getTtsModelLabel(model) }))
      if (model === ttsModel) {
        setVoiceError(message)
      }
      console.error(`刷新 ${model} 音色库失败:`, error)
    }
  }, [t, ttsModel])

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
          throw firstFailure?.reason || new Error(t('audiobook.useAudiobookVoiceCatalog.loadFailed'))
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
          setVoiceError(t('audiobook.useAudiobookVoiceCatalog.reloadFailedWithModel', { model: getTtsModelLabel(ttsModel) }))
        } else {
          setVoiceError(t('audiobook.useAudiobookVoiceCatalog.partialLoadFailed', { models: failedModels.map(getTtsModelLabel).join('、') }))
        }
      } catch (error: unknown) {
        if (!cancelled) {
          const message = await extractApiErrorMessage(error, t('audiobook.useAudiobookVoiceCatalog.loadFailed'))
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
  }, [t])

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
    voiceCatalogSummary,
    voiceCatalogNotice,
    voiceCatalogNoticeSeverity,
    refreshVoiceCatalog,
    fetchVoiceCatalog,
  }
}
