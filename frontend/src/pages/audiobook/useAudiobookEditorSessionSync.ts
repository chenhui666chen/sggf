import {
  useCallback,
  useEffect,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from 'react'

import type {
  AudiobookEditorSessionState,
  ScriptEditorChapterRef,
  ScriptEditorStateData,
  TimelineClipEditMap,
} from './types'
import {
  AUDIOBOOK_EDITOR_SYNC_HEARTBEAT_MS,
  areAudiobookEditorSessionsEquivalent,
  buildAudiobookEditorConflictSignature,
  buildAudiobookEditorSessionPayload,
  selectLatestIncomingAudiobookEditorSyncEntry,
  shouldRefreshAudiobookEditorSyncHeartbeat,
} from './editorSessionUtils'
import {
  readStoredAudiobookEditorSyncEntries,
  removeStoredAudiobookEditorSession,
  shouldPersistStoredAudiobookEditorSession,
  writeStoredAudiobookEditorSession,
  writeStoredAudiobookEditorSyncEntries,
} from './editorSessionStorageUtils'

interface UseAudiobookEditorSessionSyncParams {
  editorSessionStorageKey: string
  editorSyncStorageKey: string
  sessionHydratedRef: MutableRefObject<boolean>
  sessionTabIdRef: MutableRefObject<string>
  restoredEditorSessionKeyRef: MutableRefObject<string | null>
  dismissedEditorConflictSignatureRef: MutableRefObject<string | null>
  selectedProjectId: number | null
  audiobookProjectId?: number | null
  scriptEditorDialogOpen: boolean
  scriptEditorChapter: ScriptEditorChapterRef | null
  scriptEditorData: ScriptEditorStateData | null
  reviewMode: boolean
  segmentDetailsOpen: Record<number, boolean>
  segmentReviews: Record<number, { quality_score?: number; needs_regenerate?: boolean }>
  timelineEdits: TimelineClipEditMap
  setEditorCrossTabConflict: Dispatch<SetStateAction<AudiobookEditorSessionState | null>>
}

export const useAudiobookEditorSessionSync = ({
  editorSessionStorageKey,
  editorSyncStorageKey,
  sessionHydratedRef,
  sessionTabIdRef,
  restoredEditorSessionKeyRef,
  dismissedEditorConflictSignatureRef,
  selectedProjectId,
  audiobookProjectId,
  scriptEditorDialogOpen,
  scriptEditorChapter,
  scriptEditorData,
  reviewMode,
  segmentDetailsOpen,
  segmentReviews,
  timelineEdits,
  setEditorCrossTabConflict,
}: UseAudiobookEditorSessionSyncParams) => {
  const writeEditorSyncEntries = useCallback((
    entries: Record<string, AudiobookEditorSessionState>,
  ) => {
    if (typeof window === 'undefined') {
      return
    }

    writeStoredAudiobookEditorSyncEntries(localStorage, editorSyncStorageKey, entries)
  }, [editorSyncStorageKey])

  const readEditorSyncEntries = useCallback((rawRegistry?: string | null) => {
    if (typeof window === 'undefined') {
      return {}
    }

    const result = readStoredAudiobookEditorSyncEntries(
      localStorage,
      editorSyncStorageKey,
      rawRegistry,
    )
    if (result.pruned) {
      writeEditorSyncEntries(result.entries)
    }

    return result.entries
  }, [editorSyncStorageKey, writeEditorSyncEntries])

  const buildCurrentEditorSyncEntry = useCallback((updatedAt: string) => {
    if (
      !selectedProjectId
      || !audiobookProjectId
      || !scriptEditorChapter
      || !scriptEditorData
    ) {
      return null
    }

    return buildAudiobookEditorSessionPayload({
      projectId: selectedProjectId,
      audiobookProjectId,
      chapterId: scriptEditorChapter.chapterId,
      reviewMode,
      segmentDetailsOpen,
      segmentReviews,
      timelineEdits,
      data: scriptEditorData,
      updatedAt,
      writerTabId: sessionTabIdRef.current,
    })
  }, [
    selectedProjectId,
    audiobookProjectId,
    scriptEditorChapter,
    scriptEditorData,
    reviewMode,
    segmentDetailsOpen,
    segmentReviews,
    timelineEdits,
    sessionTabIdRef,
  ])

  const upsertCurrentEditorSyncEntry = useCallback((options?: { forceTouch?: boolean }) => {
    if (typeof window === 'undefined') {
      return
    }

    const writerTabId = sessionTabIdRef.current
    const updatedAt = new Date().toISOString()
    const nextEntry = buildCurrentEditorSyncEntry(updatedAt)
    if (!nextEntry) {
      return
    }

    try {
      const currentEntries = readEditorSyncEntries()
      const currentSelfEntry = currentEntries[writerTabId]
      const isSameDraft = currentSelfEntry
        ? areAudiobookEditorSessionsEquivalent(currentSelfEntry, nextEntry)
        : false
      const shouldRefreshHeartbeat = Boolean(
        !currentSelfEntry
        || shouldRefreshAudiobookEditorSyncHeartbeat({
          existingUpdatedAt: currentSelfEntry.updatedAt,
          forceTouch: options?.forceTouch,
        }),
      )

      if (isSameDraft && !shouldRefreshHeartbeat) {
        return
      }

      writeEditorSyncEntries({
        ...currentEntries,
        [writerTabId]: nextEntry,
      })
    } catch {
      // localStorage 不可用或容量不足时忽略跨标签页草稿同步元数据
    }
  }, [buildCurrentEditorSyncEntry, readEditorSyncEntries, sessionTabIdRef, writeEditorSyncEntries])

  const removeCurrentEditorSyncEntry = useCallback(() => {
    if (typeof window === 'undefined') {
      return
    }

    const writerTabId = sessionTabIdRef.current
    try {
      const currentEntries = readEditorSyncEntries()
      if (!currentEntries[writerTabId]) {
        return
      }

      const nextEntries = { ...currentEntries }
      delete nextEntries[writerTabId]
      writeEditorSyncEntries(nextEntries)
    } catch {
      // 忽略跨标签页草稿同步元数据清理失败
    }
  }, [readEditorSyncEntries, sessionTabIdRef, writeEditorSyncEntries])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    const handleBeforeUnload = () => {
      removeCurrentEditorSyncEntry()
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
      removeCurrentEditorSyncEntry()
    }
  }, [removeCurrentEditorSyncEntry])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !scriptEditorDialogOpen
      || !scriptEditorChapter
      || !scriptEditorData
    ) {
      return
    }

    const intervalId = window.setInterval(() => {
      upsertCurrentEditorSyncEntry({ forceTouch: true })
    }, AUDIOBOOK_EDITOR_SYNC_HEARTBEAT_MS)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [
    scriptEditorDialogOpen,
    scriptEditorChapter,
    scriptEditorData,
    sessionHydratedRef,
    upsertCurrentEditorSyncEntry,
  ])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !selectedProjectId
      || !audiobookProjectId
    ) {
      return
    }

    const restoreKey = `${selectedProjectId}:${audiobookProjectId}`
    if (restoredEditorSessionKeyRef.current !== restoreKey) {
      return
    }

    if (!scriptEditorDialogOpen || !scriptEditorChapter || !scriptEditorData) {
      removeStoredAudiobookEditorSession(sessionStorage, editorSessionStorageKey)
      removeCurrentEditorSyncEntry()
      return
    }

    const editorSessionPayload = buildAudiobookEditorSessionPayload({
      projectId: selectedProjectId,
      audiobookProjectId,
      chapterId: scriptEditorChapter.chapterId,
      reviewMode,
      segmentDetailsOpen,
      segmentReviews,
      timelineEdits,
      data: scriptEditorData,
    })

    const shouldPersistEditorSession = shouldPersistStoredAudiobookEditorSession(
      sessionStorage,
      editorSessionStorageKey,
      editorSessionPayload,
    )

    if (shouldPersistEditorSession) {
      try {
        writeStoredAudiobookEditorSession(sessionStorage, editorSessionStorageKey, editorSessionPayload)
      } catch {
        // sessionStorage 不可用或容量不足时忽略编辑器草稿持久化
      }
    }

    upsertCurrentEditorSyncEntry()
  }, [
    selectedProjectId,
    audiobookProjectId,
    scriptEditorDialogOpen,
    scriptEditorChapter,
    scriptEditorData,
    reviewMode,
    segmentDetailsOpen,
    segmentReviews,
    timelineEdits,
    editorSessionStorageKey,
    sessionHydratedRef,
    restoredEditorSessionKeyRef,
    removeCurrentEditorSyncEntry,
    upsertCurrentEditorSyncEntry,
  ])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !selectedProjectId
      || !audiobookProjectId
      || !scriptEditorDialogOpen
      || !scriptEditorChapter
      || !scriptEditorData
    ) {
      setEditorCrossTabConflict(null)
      dismissedEditorConflictSignatureRef.current = null
      return
    }

    const evaluateIncomingEditorDraft = (rawRegistry: string | null) => {
      const currentEntries = readEditorSyncEntries(rawRegistry)
      const incomingEntry = selectLatestIncomingAudiobookEditorSyncEntry(currentEntries, {
        writerTabId: sessionTabIdRef.current,
        projectId: selectedProjectId,
        audiobookProjectId,
        chapterId: scriptEditorChapter.chapterId,
      })

      if (!incomingEntry) {
        setEditorCrossTabConflict(null)
        dismissedEditorConflictSignatureRef.current = null
        return
      }

      const localDraft = buildAudiobookEditorSessionPayload({
        projectId: selectedProjectId,
        audiobookProjectId,
        chapterId: scriptEditorChapter.chapterId,
        reviewMode,
        segmentDetailsOpen,
        segmentReviews,
        timelineEdits,
        data: scriptEditorData,
      })

      if (areAudiobookEditorSessionsEquivalent(localDraft, incomingEntry)) {
        setEditorCrossTabConflict(null)
        dismissedEditorConflictSignatureRef.current = null
        return
      }

      const incomingSignature = buildAudiobookEditorConflictSignature(incomingEntry)
      if (incomingSignature && dismissedEditorConflictSignatureRef.current === incomingSignature) {
        return
      }

      setEditorCrossTabConflict(incomingEntry)
    }

    try {
      evaluateIncomingEditorDraft(localStorage.getItem(editorSyncStorageKey))
    } catch {
      setEditorCrossTabConflict(null)
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== editorSyncStorageKey) {
        return
      }
      try {
        evaluateIncomingEditorDraft(event.newValue)
      } catch {
        // 忽略其它标签页广播的无效编辑器草稿同步数据
      }
    }

    window.addEventListener('storage', handleStorage)
    return () => {
      window.removeEventListener('storage', handleStorage)
    }
  }, [
    selectedProjectId,
    audiobookProjectId,
    scriptEditorDialogOpen,
    scriptEditorChapter,
    scriptEditorData,
    reviewMode,
    segmentDetailsOpen,
    segmentReviews,
    timelineEdits,
    editorSyncStorageKey,
    sessionHydratedRef,
    sessionTabIdRef,
    dismissedEditorConflictSignatureRef,
    readEditorSyncEntries,
    setEditorCrossTabConflict,
  ])

  return {
    removeCurrentEditorSyncEntry,
  }
}
