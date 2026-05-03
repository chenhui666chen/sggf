import { useCallback } from 'react'

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
  const ensureCurrentTtsModelReady = useCallback(() => {
    if (catalogUnavailable) {
      setSnackbar({
        open: true,
        message: `${modelLabel} 音色目录不可用：${catalogError || '请检查后端 voice catalog 配置后再生成。'}`,
        severity: 'error',
      })
      return false
    }

    if (runtimeUnavailable) {
      setSnackbar({
        open: true,
        message: `${modelLabel} 运行时不可用：${runtimeError || '请检查后端 adapter 注册后再生成。'}`,
        severity: 'error',
      })
      return false
    }

    if (!requiresCustomVoice || hasUsableVoice) {
      return true
    }

    setSnackbar({
      open: true,
      message: `${modelLabel} 没有可用系统音色，请先创建或选择至少一个自定义音色再生成。`,
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
  ])

  return {
    ensureCurrentTtsModelReady,
  }
}
