import { useCallback, useState } from 'react'

import type { TaskStatus } from './types'

export const useAudiobookGenerationState = () => {
  const [generating, setGenerating] = useState(false)
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>({})
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [currentAudiobookProjectId, setCurrentAudiobookProjectId] = useState<number | null>(null)
  const [lastGenerationMode, setLastGenerationMode] = useState<'full' | 'script_only'>('script_only')
  const [activeStep, setActiveStep] = useState(0)

  const clearActiveGenerationState = useCallback(() => {
    setCurrentAudiobookProjectId(null)
    setCurrentTaskId(null)
    setTaskStatuses({})
    setGenerating(false)
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
    clearActiveGenerationState,
  }
}
