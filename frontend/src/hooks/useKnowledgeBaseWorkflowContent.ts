import { useCallback, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

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

const WORKFLOW_CONTENT_TIMEOUT_MS = 10000

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

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), WORKFLOW_CONTENT_TIMEOUT_MS)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
        },
        signal: controller.signal,
      })

      if (response.ok) {
        const data = await response.json()
        const stages = data.stages || {}
        setWorldSetting(parseWorkflowStageContent(stages.world_setting))
        setCharacters(parseWorkflowStageContent(stages.characters))
        setPlotOutline(parseWorkflowStageContent(stages.plot_outline))
        return
      }

      const errorData = await response.json().catch(() => null)
      setError(errorData?.detail || '加载失败')
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        logger.error('❌ 加载工作流数据超时')
        setError('加载超时，请重试')
      } else {
        logger.error('❌ 加载工作流数据失败:', err)
        setError('加载失败，请重试')
      }
    } finally {
      clearTimeout(timeoutId)
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
