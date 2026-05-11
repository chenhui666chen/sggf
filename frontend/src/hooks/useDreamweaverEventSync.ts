import { useState, useCallback, useRef } from 'react'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import type {
  DreamweaverAssetPlanItem,
  DreamweaverEventRecord,
  DreamweaverLibraryPlanItem,
} from '@/types/dreamweaver'
import {
  resolveTextStreamUpdate,
  normalizeAssetPlanItems as _normalizeAssetPlanItems,
  normalizeLibraryPlanItems as _normalizeLibraryPlanItems,
  mergePlanItems,
  extractAssetReadyPayload,
  resolveNotFoundRecovery,
  shouldTreatRunNotFoundAsPending as _shouldTreatRunNotFoundAsPending,
  isNotFoundError,
  toDreamweaverEventRecords,
} from '@/pages/dreamweaver-run/runPageHelpers'

export interface UseDreamweaverEventSyncOptions {
  onApplyStageSignal: (stage: string | null, payload: Record<string, unknown>) => void
  onSetError: (error: string | null) => void
  onSetTaskStatus: (status: string | null) => void
  onSetRunning: (running: boolean) => void
  onSetWaitingApproval: (waiting: boolean) => void
  onResetMissingRunState: (projectId: number | null) => void
  getSelectedProjectId: () => number | null
  getTaskId: () => string | null
  getTaskStatus: () => string | null
}

export function useDreamweaverEventSync(options: UseDreamweaverEventSyncOptions) {
  const {
    onApplyStageSignal,
    onSetError,
    onSetTaskStatus,
    onSetRunning,
    onSetWaitingApproval,
    onResetMissingRunState,
    getSelectedProjectId,
    getTaskId,
    getTaskStatus,
  } = options

  const [eventCursor, setEventCursor] = useState(0)
  const [eventSyncing, setEventSyncing] = useState(false)
  const [eventSyncError, setEventSyncError] = useState<string | null>(null)
  const [wsError, setWsError] = useState<string | null>(null)
  const [streamTextByKey, setStreamTextByKey] = useState<Record<string, string>>({})
  const [streamMetaByKey, setStreamMetaByKey] = useState<Record<string, { stage?: string | null; done?: boolean }>>({})
  const [assetPlanItems, setAssetPlanItems] = useState<DreamweaverAssetPlanItem[]>([])
  const [libraryPlanItems, setLibraryPlanItems] = useState<DreamweaverLibraryPlanItem[]>([])

  const activeRunIdRef = useRef<string | null>(null)
  const eventCursorRef = useRef(0)
  const eventSyncingRef = useRef(false)

  const resetDreamweaverEvents = useCallback(() => {
    eventCursorRef.current = 0
    setEventCursor(0)
    setEventSyncError(null)
    setStreamTextByKey({})
    setStreamMetaByKey({})
    setAssetPlanItems([])
    setLibraryPlanItems([])
  }, [])

  const applyDreamweaverEvent = useCallback(
    (event: DreamweaverEventRecord) => {
      if (!event || !event.run_id) return
      const activeRunId = activeRunIdRef.current
      if (!activeRunId || event.run_id !== activeRunId) return

      const eventId = typeof event.event_id === 'number' ? event.event_id : Number(event.event_id || 0)
      if (eventId && eventId <= eventCursorRef.current) return
      if (eventId) {
        eventCursorRef.current = eventId
        setEventCursor(eventId)
      }

      const eventType = String(event.event_type || '').trim()
      const stage = event.stage != null ? String(event.stage) : null
      const payload = event.payload || {}

      const streamUpdate = resolveTextStreamUpdate(eventType, payload, stage)
      if (streamUpdate.handled) {
        if (streamUpdate.textUpdater) setStreamTextByKey(streamUpdate.textUpdater)
        if (streamUpdate.metaUpdater) setStreamMetaByKey(streamUpdate.metaUpdater)
        return
      }

      if (eventType === 'asset_library_plan') {
        const items = _normalizeLibraryPlanItems(payload.items)
        if (items.length) {
          setLibraryPlanItems((prev) => mergePlanItems(prev, items))
        }
        return
      }

      if (eventType === 'asset_plan') {
        const items = _normalizeAssetPlanItems(payload.items)
        if (items.length) {
          setAssetPlanItems((prev) => mergePlanItems(prev, items))
        }
        return
      }

      if (eventType === 'asset_ready') {
        const ready = extractAssetReadyPayload(payload)
        if (!ready) return

        setAssetPlanItems((prev) => {
          const map = new Map(prev.map((item) => [item.id, item]))
          const existing = map.get(ready.assetId)
          const next: DreamweaverAssetPlanItem = {
            id: ready.assetId,
            shot_id: ready.shotId ?? existing?.shot_id ?? null,
            role: ready.role || existing?.role || null,
            kind: ready.kind,
            label: existing?.label || ready.assetId,
            status: 'done',
            uri: ready.uri || existing?.uri || null,
          }
          map.set(ready.assetId, { ...existing, ...next })
          return Array.from(map.values())
        })
        return
      }

      if (eventType === 'stage_start' || eventType === 'stage_progress' || eventType === 'stage_end') {
        onApplyStageSignal(stage, payload)
        return
      }

      if (eventType === 'run_error') {
        const err = typeof payload.error === 'string' ? String(payload.error || '').trim() : ''
        if (err) onSetError(err)
        onSetTaskStatus('failed')
        onSetRunning(false)
        onSetWaitingApproval(false)
      }
    },
    [onApplyStageSignal, onSetError, onSetRunning, onSetTaskStatus, onSetWaitingApproval],
  )

  const syncDreamweaverEvents = useCallback(
    async (runId: string) => {
      if (!runId) return
      if (eventSyncingRef.current) return
      eventSyncingRef.current = true
      setEventSyncing(true)
      setEventSyncError(null)

      try {
        let afterId = eventCursorRef.current
        let guard = 0
        while (guard < 6) {
          if (activeRunIdRef.current && activeRunIdRef.current !== runId) break
          const res = await apiClient.getDreamweaverRunEvents(runId, { after_id: afterId, limit: 200 })
          const rows = toDreamweaverEventRecords(res.data)
          if (!rows.length) break
          for (const row of rows) {
            applyDreamweaverEvent(row)
          }
          const maxId = rows.reduce((acc, item) => {
            const id = typeof item.event_id === 'number' ? item.event_id : Number(item.event_id || 0)
            return id > acc ? id : acc
          }, afterId)
          if (maxId > afterId) {
            afterId = maxId
            eventCursorRef.current = maxId
            setEventCursor(maxId)
          }
          if (rows.length < 200) break
          guard += 1
        }
      } catch (e: unknown) {
        const recovery = resolveNotFoundRecovery(e, getTaskId(), getTaskStatus(), {
          isNotFoundError,
          shouldTreatRunNotFoundAsPending: _shouldTreatRunNotFoundAsPending,
          pendingMessage: '事件尚未落库，稍后再试',
        })
        if (recovery.handled) {
          if (recovery.pendingMessage) {
            setEventSyncError(recovery.pendingMessage)
            return
          }
          onResetMissingRunState(getSelectedProjectId())
          return
        }
        setEventSyncError(await extractApiErrorMessage(e, '同步事件失败'))
      } finally {
        eventSyncingRef.current = false
        setEventSyncing(false)
      }
    },
    [applyDreamweaverEvent, getTaskId, getTaskStatus, getSelectedProjectId, onResetMissingRunState],
  )

  return {
    eventCursor,
    eventSyncing,
    eventSyncError,
    wsError,
    streamTextByKey,
    streamMetaByKey,
    assetPlanItems,
    libraryPlanItems,
    setEventCursor,
    setEventSyncError,
    setWsError,
    setStreamTextByKey,
    setStreamMetaByKey,
    setAssetPlanItems,
    setLibraryPlanItems,
    activeRunIdRef,
    eventCursorRef,
    eventSyncingRef,
    resetDreamweaverEvents,
    applyDreamweaverEvent,
    syncDreamweaverEvents,
  }
}
