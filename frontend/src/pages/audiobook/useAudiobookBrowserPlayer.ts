import { useCallback, useState } from 'react'

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
  const [browserPlayerOpen, setBrowserPlayerOpen] = useState(false)
  const [browserPlayerLoading, setBrowserPlayerLoading] = useState(false)
  const [browserPlayerData, setBrowserPlayerData] = useState<BrowserPlayerProjectData | null>(null)

  const resetBrowserPlayer = useCallback(() => {
    setBrowserPlayerData(null)
    setBrowserPlayerOpen(false)
  }, [])

  const handleOpenBrowserPlayer = useCallback(async () => {
    if (!audiobookProjectId) {
      setSnackbar({ open: true, message: '请先生成或加载有声书项目', severity: 'warning' })
      return
    }

    setBrowserPlayerLoading(true)
    try {
      const response = await apiClient.getBrowserPlayerData(audiobookProjectId)
      const data = response.data as BrowserPlayerProjectData

      if (!data?.chapters?.length) {
        setSnackbar({ open: true, message: '当前项目暂无可播放章节', severity: 'warning' })
        return
      }

      setBrowserPlayerData(data)
      setBrowserPlayerOpen(true)
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '加载浏览器播放器失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setBrowserPlayerLoading(false)
    }
  }, [audiobookProjectId, setSnackbar])

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
