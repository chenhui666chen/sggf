import { useEffect, useRef } from 'react'
import type { DreamweaverEventRecord } from '@/types/dreamweaver'
import { workflowWebSocket } from '@/services/websocket'

export interface UseDreamweaverEventSyncLifecycleOptions {
  selectedProjectId: number | null
  currentRunId: string | null
  running: boolean
  syncDreamweaverEvents: (runId: string) => Promise<void>
  resetDreamweaverEvents: () => void
  applyDreamweaverEvent: (data: DreamweaverEventRecord) => void
  setWsError: (error: string | null) => void
}

export function useDreamweaverEventSyncLifecycle(options: UseDreamweaverEventSyncLifecycleOptions) {
  const {
    selectedProjectId,
    currentRunId,
    running,
    syncDreamweaverEvents,
    resetDreamweaverEvents,
    applyDreamweaverEvent,
    setWsError,
  } = options

  const activeRunIdRef = useRef<string | null>(null)
  const eventSyncingRef = useRef(false)

  useEffect(() => {
    eventSyncingRef.current = true
    return () => { eventSyncingRef.current = false }
  }, [])

  useEffect(() => {
    if (!currentRunId) {
      activeRunIdRef.current = null
      resetDreamweaverEvents()
      return
    }
    if (activeRunIdRef.current === currentRunId) return
    activeRunIdRef.current = currentRunId
    resetDreamweaverEvents()
    void syncDreamweaverEvents(currentRunId)
  }, [currentRunId, resetDreamweaverEvents, syncDreamweaverEvents])

  useEffect(() => {
    if (!currentRunId) return
    if (!running) return
    const timer = window.setInterval(() => {
      if (eventSyncingRef.current) return
      void syncDreamweaverEvents(currentRunId)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [currentRunId, running, syncDreamweaverEvents])

  useEffect(() => {
    if (!selectedProjectId) return
    let active = true

    workflowWebSocket.setOnRoomJoined((joinedProjectId) => {
      if (!active) return
      if (joinedProjectId !== selectedProjectId) return
      if (activeRunIdRef.current) {
        void syncDreamweaverEvents(activeRunIdRef.current)
      }
    })

    workflowWebSocket.connect().then(() => {
      if (!active) return
      workflowWebSocket.joinProject(selectedProjectId)
    }).catch((error) => {
      setWsError(`WebSocket 连接失败: ${error instanceof Error ? error.message : String(error)}`)
    })

    workflowWebSocket.onDreamweaverEvent((data) => {
      applyDreamweaverEvent(data as DreamweaverEventRecord)
    })

    return () => {
      active = false
      workflowWebSocket.setOnRoomJoined(() => {})
      workflowWebSocket.removeEventListeners()
    }
  }, [applyDreamweaverEvent, selectedProjectId, syncDreamweaverEvents])
}
