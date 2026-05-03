import { useEffect, type Dispatch, type MutableRefObject, type SetStateAction } from 'react'

import type { ActiveTaskRef } from './taskUtils'
import type { Chapter, TaskStatus, TtsModel } from './types'
import { parseSessionTimestamp } from './editorSessionUtils'
import {
  buildAudiobookTaskSessionPayload,
  buildIncomingAudiobookTaskSessionUpdate,
  mergePendingTaskStatuses,
  readIncomingAudiobookTaskSession,
  removeStoredAudiobookTaskSession,
  shouldClearAudiobookTaskSession,
  shouldWriteAudiobookTaskSession,
  writeStoredAudiobookTaskSession,
} from './taskSessionStorageUtils'

interface UseAudiobookTaskSessionSyncParams {
  sessionStorageKey: string
  sessionHydratedRef: MutableRefObject<boolean>
  sessionTabIdRef: MutableRefObject<string>
  lastSessionTimestampRef: MutableRefObject<number>
  ttsModelRef: MutableRefObject<TtsModel>
  selectedProjectId: number | null
  currentAudiobookProjectId: number | null
  currentTaskId: string | null
  persistedActiveTaskRefs: ActiveTaskRef[]
  selectedChapters: number[]
  activeStep: number
  generating: boolean
  ttsModel: TtsModel
  chapters: Chapter[]
  currentAudiobookProjectDetailId?: number | null
  setSelectedChapters: Dispatch<SetStateAction<number[]>>
  setActiveStep: Dispatch<SetStateAction<number>>
  setTaskStatuses: Dispatch<SetStateAction<Record<string, TaskStatus>>>
  setCurrentTaskId: Dispatch<SetStateAction<string | null>>
  setCurrentAudiobookProjectId: Dispatch<SetStateAction<number | null>>
  setGenerating: Dispatch<SetStateAction<boolean>>
  setTtsModel: Dispatch<SetStateAction<TtsModel>>
  refreshAudiobookProjectDetail: (audiobookProjectId: number) => Promise<unknown>
}

export const useAudiobookTaskSessionSync = ({
  sessionStorageKey,
  sessionHydratedRef,
  sessionTabIdRef,
  lastSessionTimestampRef,
  ttsModelRef,
  selectedProjectId,
  currentAudiobookProjectId,
  currentTaskId,
  persistedActiveTaskRefs,
  selectedChapters,
  activeStep,
  generating,
  ttsModel,
  chapters,
  currentAudiobookProjectDetailId,
  setSelectedChapters,
  setActiveStep,
  setTaskStatuses,
  setCurrentTaskId,
  setCurrentAudiobookProjectId,
  setGenerating,
  setTtsModel,
  refreshAudiobookProjectDetail,
}: UseAudiobookTaskSessionSyncParams) => {
  useEffect(() => {
    if (typeof window === 'undefined' || !sessionHydratedRef.current) {
      return
    }

    if (shouldClearAudiobookTaskSession({
      selectedProjectId,
      currentAudiobookProjectId,
      currentTaskId,
    })) {
      removeStoredAudiobookTaskSession(localStorage, sessionStorageKey)
      lastSessionTimestampRef.current = 0
      return
    }

    const updatedAt = new Date().toISOString()
    const payload = buildAudiobookTaskSessionPayload({
      projectId: selectedProjectId,
      audiobookProjectId: currentAudiobookProjectId,
      taskId: currentTaskId,
      activeTasks: persistedActiveTaskRefs,
      selectedChapterIds: selectedChapters,
      activeStep,
      generating,
      ttsModel,
      updatedAt,
      writerTabId: sessionTabIdRef.current,
    })
    if (!shouldWriteAudiobookTaskSession(localStorage, sessionStorageKey, payload)) {
      return
    }

    if (writeStoredAudiobookTaskSession(localStorage, sessionStorageKey, payload)) {
      lastSessionTimestampRef.current = parseSessionTimestamp(updatedAt)
    }
  }, [
    activeStep,
    currentAudiobookProjectId,
    currentTaskId,
    generating,
    lastSessionTimestampRef,
    persistedActiveTaskRefs,
    selectedChapters,
    selectedProjectId,
    sessionHydratedRef,
    sessionStorageKey,
    sessionTabIdRef,
    ttsModel,
  ])

  useEffect(() => {
    if (typeof window === 'undefined' || !sessionHydratedRef.current || !selectedProjectId) {
      return
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== sessionStorageKey || !event.newValue) {
        return
      }

      const incoming = readIncomingAudiobookTaskSession({
        rawSession: event.newValue,
        selectedProjectId,
        writerTabId: sessionTabIdRef.current,
        lastSessionTimestamp: lastSessionTimestampRef.current,
      })
      if (!incoming) {
        return
      }

      const {
        incomingActiveTasks,
        incomingTaskId,
        incomingAudiobookProjectId,
        normalizedChapterIds,
        hasSelectedChapterIds,
        incomingActiveStep,
        incomingGenerating,
        incomingTtsModel,
      } = buildIncomingAudiobookTaskSessionUpdate({
        incomingSession: incoming.incomingSession,
        chapters,
      })

      if (incomingTtsModel && incomingTtsModel !== ttsModelRef.current) {
        setTtsModel(incomingTtsModel)
      }

      if (hasSelectedChapterIds) {
        setSelectedChapters((prev) => {
          const sameLength = prev.length === normalizedChapterIds.length
          const sameItems = sameLength && prev.every((chapterId, index) => chapterId === normalizedChapterIds[index])
          return sameItems ? prev : normalizedChapterIds
        })
      }

      if (incomingActiveStep !== null) {
        setActiveStep(incomingActiveStep)
      }

      if (incomingActiveTasks.length > 0) {
        setTaskStatuses((prev) => mergePendingTaskStatuses(prev, incomingActiveTasks))
      }

      setCurrentTaskId((prev) => prev === incomingTaskId ? prev : incomingTaskId)
      setCurrentAudiobookProjectId((prev) =>
        prev === incomingAudiobookProjectId ? prev : incomingAudiobookProjectId
      )
      setGenerating(incomingGenerating)
      if (incoming.incomingSessionTimestamp > 0) {
        lastSessionTimestampRef.current = incoming.incomingSessionTimestamp
      }

      if (
        incomingAudiobookProjectId
        && incomingAudiobookProjectId !== currentAudiobookProjectDetailId
      ) {
        void refreshAudiobookProjectDetail(incomingAudiobookProjectId)
      }
    }

    window.addEventListener('storage', handleStorage)
    return () => {
      window.removeEventListener('storage', handleStorage)
    }
  }, [
    chapters,
    currentAudiobookProjectDetailId,
    lastSessionTimestampRef,
    refreshAudiobookProjectDetail,
    selectedProjectId,
    sessionHydratedRef,
    sessionStorageKey,
    sessionTabIdRef,
    setActiveStep,
    setCurrentAudiobookProjectId,
    setCurrentTaskId,
    setGenerating,
    setSelectedChapters,
    setTaskStatuses,
    setTtsModel,
    ttsModelRef,
  ])
}
