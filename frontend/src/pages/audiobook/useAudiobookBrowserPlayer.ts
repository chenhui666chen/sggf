import { useCallback, useState } from 'react'

import { useTranslation } from 'react-i18next'

import type { BrowserPlayerProjectData } from '../../components/audiobook/browserPlayerTypes'
import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'

interface UseAudiobookBrowserPlayerParams {
  audiobookProjectId?: number | null
  setSnackbar: SetSnackbar
}

export const useAudiobookBrowserPlayer = ({
  audiobookProjectId,
  setSnackbar,
}: UseAudiobookBrowserPlayerParams) => {
  const { t } = useTranslation()
  const [browserPlayerOpen, setBrowserPlayerOpen] = useState(false)
  const [browserPlayerLoading, setBrowserPlayerLoading] = useState(false)
  const [browserPlayerData, setBrowserPlayerData] = useState<BrowserPlayerProjectData | null>(null)

  const resetBrowserPlayer = useCallback(() => {
    setBrowserPlayerData(null)
    setBrowserPlayerOpen(false)
  }, [])

  const handleOpenBrowserPlayer = useCallback(async () => {
    if (!audiobookProjectId) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookBrowserPlayer.noProject'), severity: 'warning' })
      return
    }

    setBrowserPlayerLoading(true)
    try {
      const response = await apiClient.getBrowserPlayerData(audiobookProjectId)
      const data = response.data as BrowserPlayerProjectData
      const normalizedData: BrowserPlayerProjectData = {
        ...data,
        audiobook_project_id: data.audiobook_project_id ?? data.project_id,
      }

      if (!normalizedData?.chapters?.length) {
        setSnackbar({ open: true, message: t('audiobook.useAudiobookBrowserPlayer.noPlayableChapter'), severity: 'warning' })
        return
      }

      setBrowserPlayerData(normalizedData)
      setBrowserPlayerOpen(true)
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, t('audiobook.useAudiobookBrowserPlayer.loadFailed')),
        severity: 'error',
      })
    } finally {
      setBrowserPlayerLoading(false)
    }
  }, [audiobookProjectId, setSnackbar, t])

  const handleCloseBrowserPlayer = useCallback(() => {
    setBrowserPlayerOpen(false)
  }, [])

  return {
    browserPlayerOpen,
    browserPlayerLoading,
    browserPlayerData,
    resetBrowserPlayer,
    handleOpenBrowserPlayer,
    handleCloseBrowserPlayer,
  }
}
