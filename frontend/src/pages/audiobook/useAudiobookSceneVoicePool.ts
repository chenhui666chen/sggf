import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  apiClient,
  extractApiErrorMessage,
  type VoicePoolVoiceRecord,
  type VoiceReferenceAssetRecord,
} from '../../services/api'
import type { TtsModel, VoicePreset } from './types'


const isHttpUrl = (value?: string) => Boolean(value?.startsWith('http://') || value?.startsWith('https://'))

export const useAudiobookSceneVoicePool = () => {
  const [privateAssets, setPrivateAssets] = useState<VoiceReferenceAssetRecord[]>([])
  const [publicVoices, setPublicVoices] = useState<VoicePoolVoiceRecord[]>([])
  const [taxonomy, setTaxonomy] = useState<Record<string, string[] | string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [privateResponse, publicResponse, taxonomyResponse] = await Promise.all([
        apiClient.getMyVoiceReferences(),
        apiClient.getPublicVoicePool(),
        apiClient.getVoicePoolTaxonomy(),
      ])
      setPrivateAssets(privateResponse.data.assets || [])
      setPublicVoices(publicResponse.data.voices || [])
      setTaxonomy(taxonomyResponse.data || {})
      setError(null)
    } catch (requestError: unknown) {
      setError(await extractApiErrorMessage(requestError, '加载场景音色库失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const presets = useMemo<VoicePreset[]>(() => {
    const privatePresets = privateAssets.map((asset): VoicePreset => {
      const referenceUrl = isHttpUrl(asset.source_url)
        ? asset.source_url
        : isHttpUrl(asset.storage_uri)
          ? asset.storage_uri
          : undefined
      const sourceVoiceId = asset.source_voice_id || asset.asset_id
      const isDesign = asset.authorization_basis === 'synthetic_design'
      return {
        id: `private:${asset.asset_id}`,
        speaker: sourceVoiceId,
        label: `${isDesign ? '我的设计' : '我的复刻'} · ${sourceVoiceId}`,
        category: 'custom',
        customType: isDesign ? 'design' : 'clone',
        provider: asset.provider,
        description: referenceUrl ? '已准备标准参考试听' : '需要先生成标准参考试听',
        sourceModel: (asset.source_model || '') as TtsModel,
        referenceSource: 'user_private',
        referenceAudioUrl: referenceUrl,
        voiceReferenceAssetId: asset.asset_id,
        disabled: !referenceUrl,
        disabledReason: !referenceUrl ? '请先在音色管理中生成标准参考试听' : undefined,
      }
    })
    const publicPresets = publicVoices.map((voice): VoicePreset => ({
      id: `public:${voice.publication_id}`,
      speaker: `voice_pool:${voice.publication_id}`,
      label: `公共 · ${voice.display_name}`,
      category: 'public',
      description: voice.description,
      style: voice.primary_style,
      languages: [voice.language],
      sourceModel: (voice.source_model || '') as TtsModel,
      referenceSource: 'public_pool',
      referenceAudioUrl: voice.reference_audio_url,
      voicePoolPublicationId: voice.publication_id,
    }))
    return [...privatePresets, ...publicPresets]
  }, [privateAssets, publicVoices])

  return {
    privateAssets,
    publicVoices,
    taxonomy,
    presets,
    loading,
    error,
    refresh,
  }
}
