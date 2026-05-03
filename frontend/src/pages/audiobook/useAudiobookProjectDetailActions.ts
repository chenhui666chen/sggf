import { useCallback, type Dispatch, type SetStateAction } from 'react'

import { apiClient } from '../../services/api'
import type { AudiobookProjectDetail } from './types'

interface UseAudiobookProjectDetailActionsParams {
  setAudiobookProject: Dispatch<SetStateAction<AudiobookProjectDetail | null>>
}

export const useAudiobookProjectDetailActions = ({
  setAudiobookProject,
}: UseAudiobookProjectDetailActionsParams) => {
  const refreshAudiobookProjectDetail = useCallback(async (audiobookProjectId: number) => {
    const response = await apiClient.getAudiobookProject(audiobookProjectId)
    const data = response.data
    setAudiobookProject(data)
    return data
  }, [setAudiobookProject])

  return {
    refreshAudiobookProjectDetail,
  }
}
