import { useCallback, useEffect, useMemo, useState } from 'react'

import { useTranslation } from 'react-i18next'

import {
  apiClient,
  extractApiErrorMessage,
  type VoicePoolVoiceRecord,
  type VoiceReferenceAssetRecord,
} from '../../services/api'
import type { TtsModel, VoicePreset } from './types'


const isHttpUrl = (value?: string) => Boolean(value?.startsWith('http://') || value?.startsWith('https://'))

export const useAudiobookSceneVoicePool = (enabled = true) => {
  const { t } = useTranslation()
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
      setError(await extractApiErrorMessage(requestError, t('audiobook.useAudiobookSceneVoicePool.loadFailed')))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (enabled) {
      void refresh()
    }
  }, [enabled, refresh])

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
        label: t('audiobook.useAudiobookSceneVoicePool.privateVoiceLabel', { type: t(isDesign ? 'audiobook.useAudiobookSceneVoicePool.myDesignLabel' : 'audiobook.useAudiobookSceneVoicePool.myCloneLabel'), voiceId: sourceVoiceId }),
        category: 'custom',
        customType: isDesign ? 'design' : 'clone',
        provider: asset.provider,
        description: referenceUrl ? t('audiobook.useAudiobookSceneVoicePool.referenceReady') : t('audiobook.useAudiobookSceneVoicePool.referenceNeeded'),
        sourceModel: (asset.source_model || '') as TtsModel,
        referenceSource: 'user_private',
        referenceAudioUrl: referenceUrl,
        voiceReferenceAssetId: asset.asset_id,
        disabled: !referenceUrl,
        disabledReason: !referenceUrl ? t('audiobook.useAudiobookSceneVoicePool.generateReferenceFirst') : undefined,
      }
    })
    const publicPresets = publicVoices.map((voice): VoicePreset => ({
      id: `public:${voice.publication_id}`,
      speaker: `voice_pool:${voice.publication_id}`,
      label: t('audiobook.useAudiobookSceneVoicePool.publicVoiceLabel', { name: voice.display_name }),
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
  }, [privateAssets, publicVoices, t])

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
