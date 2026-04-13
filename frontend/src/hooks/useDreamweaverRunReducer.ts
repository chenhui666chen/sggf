import { useReducer, useCallback, useRef } from 'react'
import type {
  RunResult,
  DreamweaverEventRecord,
  DreamweaverAssetPlanItem,
  DreamweaverLibraryPlanItem,
  DreamweaverProjectLockedGenerationConfig,
} from '@/types/dreamweaver'

interface DreamweaverRunState {
  running: boolean
  waitingApproval: boolean
  taskId: string | null
  taskRunId: string | null
  taskStatus: string | null
  taskQueue: string | null
  taskProgress: number
  taskState: string | null
  taskStage: string | null
  taskArtifacts: Record<string, unknown> | null
  error: string | null
  result: RunResult | null

  streamTextByKey: Record<string, string>
  streamMetaByKey: Record<string, { stage: string | null; done: boolean }>

  libraryPlanItems: DreamweaverLibraryPlanItem[]
  assetPlanItems: DreamweaverAssetPlanItem[]

  eventCursor: number
  eventSyncing: boolean
  eventSyncError: string | null

  lockedGenerationConfig: DreamweaverProjectLockedGenerationConfig | null
  lockedGenerationConfigLoading: boolean
  lockedGenerationConfigError: string | null
}

type DreamweaverRunAction =
  | { type: 'START_RUN'; payload: { taskId: string; runId: string } }
  | { type: 'SET_TASK_STATUS'; payload: { status: string; queue?: string } }
  | { type: 'SET_TASK_PROGRESS'; payload: number }
  | { type: 'SET_TASK_STAGE'; payload: string }
  | { type: 'SET_TASK_STATE'; payload: string }
  | { type: 'SET_TASK_ARTIFACTS'; payload: Record<string, unknown> | null }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'SET_RESULT'; payload: RunResult | null }
  | { type: 'SET_WAITING_APPROVAL'; payload: boolean }
  | { type: 'COMPLETE_RUN' }
  | { type: 'FAIL_RUN'; payload: string }
  | { type: 'RESET_RUN' }
  | { type: 'STREAM_START'; payload: { key: string; stage: string | null } }
  | { type: 'STREAM_DELTA'; payload: { key: string; chunk: string } }
  | { type: 'STREAM_END'; payload: { key: string } }
  | { type: 'UPDATE_LIBRARY_PLAN'; payload: DreamweaverLibraryPlanItem[] }
  | { type: 'UPDATE_ASSET_PLAN'; payload: DreamweaverAssetPlanItem[] }
  | { type: 'ASSET_READY'; payload: { id: string; uri: string; kind: 'image' | 'video' } }
  | { type: 'SET_EVENT_CURSOR'; payload: number }
  | { type: 'SET_EVENT_SYNCING'; payload: boolean }
  | { type: 'SET_EVENT_SYNC_ERROR'; payload: string | null }
  | { type: 'SET_LOCKED_CONFIG'; payload: DreamweaverProjectLockedGenerationConfig | null }
  | { type: 'SET_LOCKED_CONFIG_LOADING'; payload: boolean }
  | { type: 'SET_LOCKED_CONFIG_ERROR'; payload: string | null }

const initialState: DreamweaverRunState = {
  running: false,
  waitingApproval: false,
  taskId: null,
  taskRunId: null,
  taskStatus: null,
  taskQueue: null,
  taskProgress: 0,
  taskState: null,
  taskStage: null,
  taskArtifacts: null,
  error: null,
  result: null,
  streamTextByKey: {},
  streamMetaByKey: {},
  libraryPlanItems: [],
  assetPlanItems: [],
  eventCursor: 0,
  eventSyncing: false,
  eventSyncError: null,
  lockedGenerationConfig: null,
  lockedGenerationConfigLoading: false,
  lockedGenerationConfigError: null,
}

function dreamweaverRunReducer(
  state: DreamweaverRunState,
  action: DreamweaverRunAction
): DreamweaverRunState {
  switch (action.type) {
    case 'START_RUN':
      return {
        ...state,
        running: true,
        waitingApproval: false,
        taskId: action.payload.taskId,
        taskRunId: action.payload.runId,
        taskStatus: 'queued',
        taskProgress: 0,
        error: null,
        result: null,
        streamTextByKey: {},
        streamMetaByKey: {},
        libraryPlanItems: [],
        assetPlanItems: [],
      }

    case 'SET_TASK_STATUS':
      return {
        ...state,
        taskStatus: action.payload.status,
        taskQueue: action.payload.queue ?? state.taskQueue,
      }

    case 'SET_TASK_PROGRESS':
      return { ...state, taskProgress: action.payload }

    case 'SET_TASK_STAGE':
      return { ...state, taskStage: action.payload }

    case 'SET_TASK_STATE':
      return { ...state, taskState: action.payload }

    case 'SET_TASK_ARTIFACTS':
      return { ...state, taskArtifacts: action.payload }

    case 'SET_ERROR':
      return { ...state, error: action.payload }

    case 'SET_RESULT':
      return { ...state, result: action.payload }

    case 'SET_WAITING_APPROVAL':
      return { ...state, waitingApproval: action.payload, running: !action.payload }

    case 'COMPLETE_RUN':
      return {
        ...state,
        running: false,
        waitingApproval: false,
        taskStatus: 'completed',
      }

    case 'FAIL_RUN':
      return {
        ...state,
        running: false,
        waitingApproval: false,
        taskStatus: 'failed',
        error: action.payload,
      }

    case 'RESET_RUN':
      return {
        ...initialState,
        lockedGenerationConfig: state.lockedGenerationConfig,
        lockedGenerationConfigLoading: state.lockedGenerationConfigLoading,
        lockedGenerationConfigError: state.lockedGenerationConfigError,
      }

    case 'STREAM_START':
      return {
        ...state,
        streamTextByKey: { ...state.streamTextByKey, [action.payload.key]: '' },
        streamMetaByKey: {
          ...state.streamMetaByKey,
          [action.payload.key]: { stage: action.payload.stage, done: false },
        },
      }

    case 'STREAM_DELTA':
      return {
        ...state,
        streamTextByKey: {
          ...state.streamTextByKey,
          [action.payload.key]: (state.streamTextByKey[action.payload.key] || '') + action.payload.chunk,
        },
      }

    case 'STREAM_END':
      return {
        ...state,
        streamMetaByKey: {
          ...state.streamMetaByKey,
          [action.payload.key]: { ...state.streamMetaByKey[action.payload.key], done: true },
        },
      }

    case 'UPDATE_LIBRARY_PLAN': {
      const map = new Map(state.libraryPlanItems.map((item) => [item.id, item]))
      for (const item of action.payload) {
        const existing = map.get(item.id)
        if (existing) {
          map.set(item.id, {
            ...existing,
            ...item,
            status: existing.status === 'done' ? 'done' : item.status,
            uri: existing.uri || item.uri,
          })
        } else {
          map.set(item.id, item)
        }
      }
      return { ...state, libraryPlanItems: Array.from(map.values()) }
    }

    case 'UPDATE_ASSET_PLAN': {
      const map = new Map(state.assetPlanItems.map((item) => [item.id, item]))
      for (const item of action.payload) {
        const existing = map.get(item.id)
        if (existing) {
          map.set(item.id, {
            ...item,
            status: existing.status === 'done' ? 'done' : item.status,
            uri: existing.uri || item.uri,
          })
        } else {
          map.set(item.id, item)
        }
      }
      return { ...state, assetPlanItems: Array.from(map.values()) }
    }

    case 'ASSET_READY': {
      const map = new Map(state.assetPlanItems.map((item) => [item.id, item]))
      const existing = map.get(action.payload.id)
      if (existing) {
        map.set(action.payload.id, {
          ...existing,
          status: 'done',
          uri: action.payload.uri,
          kind: action.payload.kind,
        })
      } else {
        map.set(action.payload.id, {
          id: action.payload.id,
          status: 'done',
          uri: action.payload.uri,
          kind: action.payload.kind,
          label: action.payload.id,
        } as DreamweaverAssetPlanItem)
      }
      return { ...state, assetPlanItems: Array.from(map.values()) }
    }

    case 'SET_EVENT_CURSOR':
      return { ...state, eventCursor: action.payload }

    case 'SET_EVENT_SYNCING':
      return { ...state, eventSyncing: action.payload }

    case 'SET_EVENT_SYNC_ERROR':
      return { ...state, eventSyncError: action.payload }

    case 'SET_LOCKED_CONFIG':
      return { ...state, lockedGenerationConfig: action.payload }

    case 'SET_LOCKED_CONFIG_LOADING':
      return { ...state, lockedGenerationConfigLoading: action.payload }

    case 'SET_LOCKED_CONFIG_ERROR':
      return { ...state, lockedGenerationConfigError: action.payload }

    default:
      return state
  }
}

export function useDreamweaverRunReducer() {
  const [state, dispatch] = useReducer(dreamweaverRunReducer, initialState)
  const activeRunIdRef = useRef<string | null>(null)

  const startRun = useCallback((taskId: string, runId: string) => {
    activeRunIdRef.current = runId
    dispatch({ type: 'START_RUN', payload: { taskId, runId } })
  }, [])

  const setTaskStatus = useCallback((status: string, queue?: string) => {
    dispatch({ type: 'SET_TASK_STATUS', payload: { status, queue } })
  }, [])

  const setTaskProgress = useCallback((progress: number) => {
    dispatch({ type: 'SET_TASK_PROGRESS', payload: progress })
  }, [])

  const setTaskStage = useCallback((stage: string) => {
    dispatch({ type: 'SET_TASK_STAGE', payload: stage })
  }, [])

  const setTaskState = useCallback((taskState: string) => {
    dispatch({ type: 'SET_TASK_STATE', payload: taskState })
  }, [])

  const setTaskArtifacts = useCallback((artifacts: Record<string, unknown> | null) => {
    dispatch({ type: 'SET_TASK_ARTIFACTS', payload: artifacts })
  }, [])

  const setError = useCallback((error: string | null) => {
    dispatch({ type: 'SET_ERROR', payload: error })
  }, [])

  const setResult = useCallback((result: RunResult | null) => {
    dispatch({ type: 'SET_RESULT', payload: result })
  }, [])

  const setWaitingApproval = useCallback((waiting: boolean) => {
    dispatch({ type: 'SET_WAITING_APPROVAL', payload: waiting })
  }, [])

  const completeRun = useCallback(() => {
    dispatch({ type: 'COMPLETE_RUN' })
  }, [])

  const failRun = useCallback((error: string) => {
    dispatch({ type: 'FAIL_RUN', payload: error })
  }, [])

  const resetRun = useCallback(() => {
    activeRunIdRef.current = null
    dispatch({ type: 'RESET_RUN' })
  }, [])

  const handleStreamEvent = useCallback((event: DreamweaverEventRecord) => {
    if (!event.run_id || event.run_id !== activeRunIdRef.current) return

    const eventType = event.event_type
    const payload = event.payload || {}
    const stage = event.stage ?? null

    if (eventType === 'text_stream_start') {
      const key = (payload.stream_key as string) || stage || 'default'
      dispatch({ type: 'STREAM_START', payload: { key, stage } })
    } else if (eventType === 'text_stream_delta') {
      const key = (payload.stream_key as string) || stage || 'default'
      const chunk = payload.chunk as string
      if (chunk) {
        dispatch({ type: 'STREAM_DELTA', payload: { key, chunk } })
      }
    } else if (eventType === 'text_stream_end') {
      const key = (payload.stream_key as string) || stage || 'default'
      dispatch({ type: 'STREAM_END', payload: { key } })
    } else if (eventType === 'stage_start' || eventType === 'stage_progress' || eventType === 'stage_end') {
      if (stage) dispatch({ type: 'SET_TASK_STAGE', payload: stage })
      if (payload.state) dispatch({ type: 'SET_TASK_STATE', payload: payload.state as string })
      if (typeof payload.progress === 'number') dispatch({ type: 'SET_TASK_PROGRESS', payload: payload.progress })
    } else if (eventType === 'run_error') {
      const err = payload.error as string
      if (err) dispatch({ type: 'FAIL_RUN', payload: err })
    }
  }, [])

  return {
    state,
    dispatch,
    activeRunIdRef,
    startRun,
    setTaskStatus,
    setTaskProgress,
    setTaskStage,
    setTaskState,
    setTaskArtifacts,
    setError,
    setResult,
    setWaitingApproval,
    completeRun,
    failRun,
    resetRun,
    handleStreamEvent,
  }
}

export type { DreamweaverRunState, DreamweaverRunAction }
