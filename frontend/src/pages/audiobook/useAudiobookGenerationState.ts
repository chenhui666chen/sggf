import { useCallback, useState } from 'react'

import type { TaskStatus } from './types'

export const useAudiobookGenerationState = () => {
  const [generating, setGenerating] = useState(false)
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>({})
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [currentAudiobookProjectId, setCurrentAudiobookProjectId] = useState<number | null>(null)
  const [lastGenerationMode, setLastGenerationMode] = useState<'full' | 'script_only'>('script_only')
  const [activeStep, setActiveStep] = useState(0)
  // 用户主动离开进度页后置为 true，防止任务轮询将其强制切回进度页；
  // 任务终态（完成/失败）或用户主动回到进度页时重置。
  const [progressViewDismissed, setProgressViewDismissed] = useState(false)

  const clearActiveGenerationState = useCallback(() => {
    setCurrentAudiobookProjectId(null)
    setCurrentTaskId(null)
    setTaskStatuses({})
    setGenerating(false)
    setProgressViewDismissed(false)
  }, [])

  return {
    generating,
    setGenerating,
    taskStatuses,
    setTaskStatuses,
    currentTaskId,
    setCurrentTaskId,
    currentAudiobookProjectId,
    setCurrentAudiobookProjectId,
    lastGenerationMode,
    setLastGenerationMode,
    activeStep,
    setActiveStep,
    progressViewDismissed,
    setProgressViewDismissed,
    clearActiveGenerationState,
  }
}
