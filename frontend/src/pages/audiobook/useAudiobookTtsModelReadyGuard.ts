import { useCallback } from 'react'

import { useTranslation } from 'react-i18next'

import type { SetSnackbar } from './hookTypes'

interface UseAudiobookTtsModelReadyGuardParams {
  modelLabel: string
  requiresCustomVoice: boolean
  hasUsableVoice: boolean
  catalogUnavailable: boolean
  catalogError?: string | null
  runtimeUnavailable: boolean
  runtimeError?: string | null
  setSnackbar: SetSnackbar
}

export const useAudiobookTtsModelReadyGuard = ({
  modelLabel,
  requiresCustomVoice,
  hasUsableVoice,
  catalogUnavailable,
  catalogError,
  runtimeUnavailable,
  runtimeError,
  setSnackbar,
}: UseAudiobookTtsModelReadyGuardParams) => {
  const { t } = useTranslation()
  const ensureCurrentTtsModelReady = useCallback(() => {
    if (catalogUnavailable) {
      setSnackbar({
        open: true,
        message: t('audiobook.useAudiobookTtsModelReadyGuard.catalogUnavailable', {
          model: modelLabel,
          reason: catalogError || t('audiobook.useAudiobookTtsModelReadyGuard.catalogUnavailableHint'),
        }),
        severity: 'error',
      })
      return false
    }

    if (runtimeUnavailable) {
      setSnackbar({
        open: true,
        message: t('audiobook.useAudiobookTtsModelReadyGuard.runtimeUnavailable', {
          model: modelLabel,
          reason: runtimeError || t('audiobook.useAudiobookTtsModelReadyGuard.runtimeUnavailableHint'),
        }),
        severity: 'error',
      })
      return false
    }

    if (!requiresCustomVoice || hasUsableVoice) {
      return true
    }

    setSnackbar({
      open: true,
      message: t('audiobook.useAudiobookTtsModelReadyGuard.noSystemVoices', { model: modelLabel }),
      severity: 'error',
    })
    return false
  }, [
    catalogError,
    catalogUnavailable,
    hasUsableVoice,
    modelLabel,
    requiresCustomVoice,
    runtimeError,
    runtimeUnavailable,
    setSnackbar,
    t,
  ])

  return {
    ensureCurrentTtsModelReady,
  }
}
