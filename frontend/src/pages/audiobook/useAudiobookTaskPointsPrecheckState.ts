import { useCallback, useState } from 'react'

import type { TaskPointsPrecheckErrorDetail } from '../../services/api'

export const useAudiobookTaskPointsPrecheckState = () => {
  const [taskPointsPrecheckError, setTaskPointsPrecheckError] =
    useState<TaskPointsPrecheckErrorDetail | null>(null)

  const clearTaskPointsPrecheckError = useCallback(() => {
    setTaskPointsPrecheckError(null)
  }, [])

  return {
    taskPointsPrecheckError,
    setTaskPointsPrecheckError,
    clearTaskPointsPrecheckError,
  }
}
