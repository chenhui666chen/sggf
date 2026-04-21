import { useCallback, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

import { apiClient } from '@/services/api'
import { logger } from '@/utils/logger'
import { parseWorkflowStageContent } from '@/utils/workflowStageContent'

interface UseKnowledgeBaseWorkflowContentReturn {
  loading: boolean
  error: string | null
  worldSetting: string
  setWorldSetting: Dispatch<SetStateAction<string>>
  characters: string
  setCharacters: Dispatch<SetStateAction<string>>
  plotOutline: string
  setPlotOutline: Dispatch<SetStateAction<string>>
  loadWorkflowData: () => Promise<void>
}

export function useKnowledgeBaseWorkflowContent(
  projectId?: string,
): UseKnowledgeBaseWorkflowContentReturn {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [worldSetting, setWorldSetting] = useState('')
  const [characters, setCharacters] = useState('')
  const [plotOutline, setPlotOutline] = useState('')

  const loadWorkflowData = useCallback(async () => {
    if (!projectId) {
      return
    }

    setLoading(true)
    setError(null)

    try {
      const response = await apiClient.getWorkflowAllStagesContent(Number(projectId))
      if (response.status >= 200 && response.status < 300) {
        const data = response.data || {}
        const stages = data.stages || {}
        setWorldSetting(parseWorkflowStageContent(stages.world_setting))
        setCharacters(parseWorkflowStageContent(stages.characters))
        setPlotOutline(parseWorkflowStageContent(stages.plot_outline))
        return
      }

      setError(String(response.data?.detail || response.data?.error || '加载失败'))
    } catch (err) {
      logger.error('❌ 加载工作流数据失败:', err)
      setError('加载失败，请重试')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  return {
    loading,
    error,
    worldSetting,
    setWorldSetting,
    characters,
    setCharacters,
    plotOutline,
    setPlotOutline,
    loadWorkflowData,
  }
}
