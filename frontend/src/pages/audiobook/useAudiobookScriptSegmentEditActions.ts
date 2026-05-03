import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'

import type { ScriptEditorStateData, ScriptSegment, SmartChunkPreviewResult } from './types'

interface UseAudiobookScriptSegmentEditActionsParams {
  setScriptEditorData: Dispatch<SetStateAction<ScriptEditorStateData | null>>
  setSmartChunkPreview?: Dispatch<SetStateAction<SmartChunkPreviewResult | null>>
}

export const useAudiobookScriptSegmentEditActions = ({
  setScriptEditorData,
  setSmartChunkPreview,
}: UseAudiobookScriptSegmentEditActionsParams) => {
  const [segmentDetailsOpen, setSegmentDetailsOpen] = useState<Record<number, boolean>>({})

  const resetSegmentDetailsOpen = useCallback(() => {
    setSegmentDetailsOpen({})
  }, [])

  const handleToggleSegmentDetails = useCallback((index: number) => {
    setSegmentDetailsOpen((prev) => ({ ...prev, [index]: !prev[index] }))
  }, [])

  const handleChangeScriptSegmentText = useCallback((index: number, value: string) => {
    setSmartChunkPreview?.(null)
    setScriptEditorData((prev) => {
      if (!prev) return prev
      const segments = [...prev.scriptSegments]
      segments[index] = { ...segments[index], text: value }
      return { ...prev, scriptSegments: segments }
    })
  }, [setScriptEditorData, setSmartChunkPreview])

  const handleUpdateScriptSegment = useCallback((index: number, patch: Partial<ScriptSegment>) => {
    setSmartChunkPreview?.(null)
    setScriptEditorData((prev) => {
      if (!prev) return prev
      const segments = [...prev.scriptSegments]
      segments[index] = { ...segments[index], ...patch }
      return { ...prev, scriptSegments: segments }
    })
  }, [setScriptEditorData, setSmartChunkPreview])

  return {
    segmentDetailsOpen,
    setSegmentDetailsOpen,
    resetSegmentDetailsOpen,
    handleToggleSegmentDetails,
    handleChangeScriptSegmentText,
    handleUpdateScriptSegment,
  }
}
