import { describe, expect, it } from 'vitest'
import type { DreamweaverRunState, DreamweaverRunAction } from '../useDreamweaverRunReducer'

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

function reducer(state: DreamweaverRunState, action: DreamweaverRunAction): DreamweaverRunState {
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
      return { ...state, taskStatus: action.payload.status, taskQueue: action.payload.queue ?? state.taskQueue }
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
      return { ...state, running: false, waitingApproval: false, taskStatus: 'completed' }
    case 'FAIL_RUN':
      return { ...state, running: false, waitingApproval: false, taskStatus: 'failed', error: action.payload }
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
          map.set(item.id, { ...existing, ...item, status: existing.status === 'done' ? 'done' : item.status, uri: existing.uri || item.uri })
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
          map.set(item.id, { ...item, status: existing.status === 'done' ? 'done' : item.status, uri: existing.uri || item.uri })
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
        map.set(action.payload.id, { ...existing, status: 'done', uri: action.payload.uri, kind: action.payload.kind })
      } else {
        map.set(action.payload.id, { id: action.payload.id, status: 'done', uri: action.payload.uri, kind: action.payload.kind, label: action.payload.id } as any)
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

describe('dreamweaverRunReducer', () => {
  it('初始状态应有正确的默认值', () => {
    expect(initialState.running).toBe(false)
    expect(initialState.waitingApproval).toBe(false)
    expect(initialState.taskId).toBeNull()
    expect(initialState.taskProgress).toBe(0)
    expect(initialState.error).toBeNull()
    expect(initialState.result).toBeNull()
    expect(initialState.streamTextByKey).toEqual({})
    expect(initialState.libraryPlanItems).toEqual([])
    expect(initialState.assetPlanItems).toEqual([])
  })

  describe('START_RUN', () => {
    it('应正确设置运行状态', () => {
      const next = reducer(initialState, { type: 'START_RUN', payload: { taskId: 'task-1', runId: 'run-1' } })
      expect(next.running).toBe(true)
      expect(next.waitingApproval).toBe(false)
      expect(next.taskId).toBe('task-1')
      expect(next.taskRunId).toBe('run-1')
      expect(next.taskStatus).toBe('queued')
      expect(next.taskProgress).toBe(0)
      expect(next.error).toBeNull()
      expect(next.result).toBeNull()
    })

    it('应清空之前的流和计划数据', () => {
      const withData: DreamweaverRunState = {
        ...initialState,
        streamTextByKey: { key1: 'text' },
        streamMetaByKey: { key1: { stage: 's1', done: true } },
        libraryPlanItems: [{ id: 'l1', status: 'done', uri: 'x' } as any],
        assetPlanItems: [{ id: 'a1', status: 'pending', uri: '' } as any],
      }
      const next = reducer(withData, { type: 'START_RUN', payload: { taskId: 'task-2', runId: 'run-2' } })
      expect(next.streamTextByKey).toEqual({})
      expect(next.streamMetaByKey).toEqual({})
      expect(next.libraryPlanItems).toEqual([])
      expect(next.assetPlanItems).toEqual([])
    })
  })

  describe('SET_TASK_STATUS', () => {
    it('应更新任务状态', () => {
      const started = reducer(initialState, { type: 'START_RUN', payload: { taskId: 't1', runId: 'r1' } })
      const next = reducer(started, { type: 'SET_TASK_STATUS', payload: { status: 'running' } })
      expect(next.taskStatus).toBe('running')
    })

    it('应可选更新队列名', () => {
      const next = reducer(initialState, { type: 'SET_TASK_STATUS', payload: { status: 'queued', queue: 'gpu' } })
      expect(next.taskQueue).toBe('gpu')
    })

    it('不传队列名时应保留原队列', () => {
      const withQueue = { ...initialState, taskQueue: 'cpu' }
      const next = reducer(withQueue, { type: 'SET_TASK_STATUS', payload: { status: 'running' } })
      expect(next.taskQueue).toBe('cpu')
    })
  })

  describe('SET_TASK_PROGRESS', () => {
    it('应更新进度值', () => {
      const next = reducer(initialState, { type: 'SET_TASK_PROGRESS', payload: 42 })
      expect(next.taskProgress).toBe(42)
    })
  })

  describe('COMPLETE_RUN', () => {
    it('应结束运行并设置状态为 completed', () => {
      const running = reducer(initialState, { type: 'START_RUN', payload: { taskId: 't1', runId: 'r1' } })
      const next = reducer(running, { type: 'COMPLETE_RUN' })
      expect(next.running).toBe(false)
      expect(next.waitingApproval).toBe(false)
      expect(next.taskStatus).toBe('completed')
    })
  })

  describe('FAIL_RUN', () => {
    it('应结束运行并设置错误信息', () => {
      const running = reducer(initialState, { type: 'START_RUN', payload: { taskId: 't1', runId: 'r1' } })
      const next = reducer(running, { type: 'FAIL_RUN', payload: '生成失败' })
      expect(next.running).toBe(false)
      expect(next.waitingApproval).toBe(false)
      expect(next.taskStatus).toBe('failed')
      expect(next.error).toBe('生成失败')
    })
  })

  describe('RESET_RUN', () => {
    it('应恢复初始状态但保留锁定配置', () => {
      const running = reducer(initialState, { type: 'START_RUN', payload: { taskId: 't1', runId: 'r1' } })
      const withConfig = { ...running, lockedGenerationConfig: { model_id: 'm1' } as any, lockedGenerationConfigLoading: true }
      const next = reducer(withConfig, { type: 'RESET_RUN' })
      expect(next.running).toBe(false)
      expect(next.taskId).toBeNull()
      expect(next.error).toBeNull()
      expect(next.lockedGenerationConfig).toEqual({ model_id: 'm1' })
      expect(next.lockedGenerationConfigLoading).toBe(true)
    })
  })

  describe('SET_WAITING_APPROVAL', () => {
    it('等待审核时应暂停运行', () => {
      const running = reducer(initialState, { type: 'START_RUN', payload: { taskId: 't1', runId: 'r1' } })
      const next = reducer(running, { type: 'SET_WAITING_APPROVAL', payload: true })
      expect(next.waitingApproval).toBe(true)
      expect(next.running).toBe(false)
    })

    it('取消等待时应恢复运行', () => {
      const waiting: DreamweaverRunState = { ...initialState, running: false, waitingApproval: true }
      const next = reducer(waiting, { type: 'SET_WAITING_APPROVAL', payload: false })
      expect(next.waitingApproval).toBe(false)
      expect(next.running).toBe(true)
    })
  })

  describe('流式事件', () => {
    it('STREAM_START 应初始化流文本和元数据', () => {
      const next = reducer(initialState, { type: 'STREAM_START', payload: { key: 'prompt-1', stage: 'script' } })
      expect(next.streamTextByKey['prompt-1']).toBe('')
      expect(next.streamMetaByKey['prompt-1']).toEqual({ stage: 'script', done: false })
    })

    it('STREAM_DELTA 应追加文本块', () => {
      const started = reducer(initialState, { type: 'STREAM_START', payload: { key: 'k1', stage: null } })
      const d1 = reducer(started, { type: 'STREAM_DELTA', payload: { key: 'k1', chunk: 'Hello' } })
      const d2 = reducer(d1, { type: 'STREAM_DELTA', payload: { key: 'k1', chunk: ' World' } })
      expect(d2.streamTextByKey['k1']).toBe('Hello World')
    })

    it('STREAM_END 应标记完成', () => {
      const started = reducer(initialState, { type: 'STREAM_START', payload: { key: 'k1', stage: 's' } })
      const ended = reducer(started, { type: 'STREAM_END', payload: { key: 'k1' } })
      expect(ended.streamMetaByKey['k1'].done).toBe(true)
    })

    it('多个流应独立管理', () => {
      const s1 = reducer(initialState, { type: 'STREAM_START', payload: { key: 'a', stage: null } })
      const s2 = reducer(s1, { type: 'STREAM_START', payload: { key: 'b', stage: null } })
      const d1 = reducer(s2, { type: 'STREAM_DELTA', payload: { key: 'a', chunk: 'text-a' } })
      const d2 = reducer(d1, { type: 'STREAM_DELTA', payload: { key: 'b', chunk: 'text-b' } })
      expect(d2.streamTextByKey['a']).toBe('text-a')
      expect(d2.streamTextByKey['b']).toBe('text-b')
    })
  })

  describe('UPDATE_LIBRARY_PLAN', () => {
    it('应添加新项目', () => {
      const next = reducer(initialState, {
        type: 'UPDATE_LIBRARY_PLAN',
        payload: [{ id: 'l1', status: 'pending', uri: '' } as any],
      })
      expect(next.libraryPlanItems).toHaveLength(1)
      expect(next.libraryPlanItems[0].id).toBe('l1')
    })

    it('应合并已有项目但保留 done 状态和已有 uri', () => {
      const withItem: DreamweaverRunState = {
        ...initialState,
        libraryPlanItems: [{ id: 'l1', status: 'done', uri: 'http://img.png' } as any],
      }
      const next = reducer(withItem, {
        type: 'UPDATE_LIBRARY_PLAN',
        payload: [{ id: 'l1', status: 'pending', uri: '' } as any],
      })
      expect(next.libraryPlanItems).toHaveLength(1)
      expect(next.libraryPlanItems[0].status).toBe('done')
      expect(next.libraryPlanItems[0].uri).toBe('http://img.png')
    })

    it('应合并新字段', () => {
      const withItem: DreamweaverRunState = {
        ...initialState,
        libraryPlanItems: [{ id: 'l1', status: 'pending', uri: '', label: 'old' } as any],
      }
      const next = reducer(withItem, {
        type: 'UPDATE_LIBRARY_PLAN',
        payload: [{ id: 'l1', status: 'generating', uri: 'http://new.png', label: 'new' } as any],
      })
      expect(next.libraryPlanItems[0].status).toBe('generating')
      expect(next.libraryPlanItems[0].uri).toBe('http://new.png')
      expect(next.libraryPlanItems[0].label).toBe('new')
    })
  })

  describe('UPDATE_ASSET_PLAN', () => {
    it('应添加新项目', () => {
      const next = reducer(initialState, {
        type: 'UPDATE_ASSET_PLAN',
        payload: [{ id: 'a1', status: 'pending', uri: '' } as any],
      })
      expect(next.assetPlanItems).toHaveLength(1)
    })

    it('应保留 done 状态和已有 uri', () => {
      const withItem: DreamweaverRunState = {
        ...initialState,
        assetPlanItems: [{ id: 'a1', status: 'done', uri: 'http://done.png' } as any],
      }
      const next = reducer(withItem, {
        type: 'UPDATE_ASSET_PLAN',
        payload: [{ id: 'a1', status: 'pending', uri: '' } as any],
      })
      expect(next.assetPlanItems[0].status).toBe('done')
      expect(next.assetPlanItems[0].uri).toBe('http://done.png')
    })
  })

  describe('ASSET_READY', () => {
    it('应将已有资产标记为 done', () => {
      const withItem: DreamweaverRunState = {
        ...initialState,
        assetPlanItems: [{ id: 'a1', status: 'generating', uri: '', kind: 'image', label: '角色1' } as any],
      }
      const next = reducer(withItem, { type: 'ASSET_READY', payload: { id: 'a1', uri: 'http://ready.png', kind: 'image' } })
      expect(next.assetPlanItems[0].status).toBe('done')
      expect(next.assetPlanItems[0].uri).toBe('http://ready.png')
    })

    it('应添加未知资产', () => {
      const next = reducer(initialState, { type: 'ASSET_READY', payload: { id: 'a-new', uri: 'http://new.png', kind: 'video' } })
      expect(next.assetPlanItems).toHaveLength(1)
      expect(next.assetPlanItems[0].id).toBe('a-new')
      expect(next.assetPlanItems[0].status).toBe('done')
    })
  })

  describe('SET_LOCKED_CONFIG', () => {
    it('应设置锁定配置', () => {
      const config = { model_id: 'm1', quality_mode: 'quality' } as any
      const next = reducer(initialState, { type: 'SET_LOCKED_CONFIG', payload: config })
      expect(next.lockedGenerationConfig).toEqual(config)
    })

    it('应支持设为 null', () => {
      const withConfig = { ...initialState, lockedGenerationConfig: { model_id: 'm1' } as any }
      const next = reducer(withConfig, { type: 'SET_LOCKED_CONFIG', payload: null })
      expect(next.lockedGenerationConfig).toBeNull()
    })
  })

  describe('事件同步', () => {
    it('SET_EVENT_CURSOR 应更新游标', () => {
      const next = reducer(initialState, { type: 'SET_EVENT_CURSOR', payload: 42 })
      expect(next.eventCursor).toBe(42)
    })

    it('SET_EVENT_SYNCING 应更新同步状态', () => {
      const next = reducer(initialState, { type: 'SET_EVENT_SYNCING', payload: true })
      expect(next.eventSyncing).toBe(true)
    })

    it('SET_EVENT_SYNC_ERROR 应更新错误', () => {
      const next = reducer(initialState, { type: 'SET_EVENT_SYNC_ERROR', payload: '连接超时' })
      expect(next.eventSyncError).toBe('连接超时')
    })
  })

  describe('完整运行流程', () => {
    it('应正确处理完整的运行生命周期', () => {
      let state = reducer(initialState, { type: 'START_RUN', payload: { taskId: 't1', runId: 'r1' } })
      expect(state.running).toBe(true)
      expect(state.taskStatus).toBe('queued')

      state = reducer(state, { type: 'SET_TASK_STATUS', payload: { status: 'running' } })
      expect(state.taskStatus).toBe('running')

      state = reducer(state, { type: 'SET_TASK_PROGRESS', payload: 50 })
      expect(state.taskProgress).toBe(50)

      state = reducer(state, { type: 'SET_TASK_STAGE', payload: 'video_generation' })
      expect(state.taskStage).toBe('video_generation')

      state = reducer(state, { type: 'SET_WAITING_APPROVAL', payload: true })
      expect(state.waitingApproval).toBe(true)
      expect(state.running).toBe(false)

      state = reducer(state, { type: 'SET_WAITING_APPROVAL', payload: false })
      expect(state.waitingApproval).toBe(false)
      expect(state.running).toBe(true)

      state = reducer(state, { type: 'COMPLETE_RUN' })
      expect(state.running).toBe(false)
      expect(state.taskStatus).toBe('completed')
    })

    it('应正确处理失败流程', () => {
      let state = reducer(initialState, { type: 'START_RUN', payload: { taskId: 't1', runId: 'r1' } })
      state = reducer(state, { type: 'FAIL_RUN', payload: 'GPU 不可用' })
      expect(state.running).toBe(false)
      expect(state.taskStatus).toBe('failed')
      expect(state.error).toBe('GPU 不可用')
    })

    it('应正确处理重置后重新运行', () => {
      let state = reducer(initialState, { type: 'START_RUN', payload: { taskId: 't1', runId: 'r1' } })
      state = reducer(state, { type: 'FAIL_RUN', payload: '错误' })
      state = reducer(state, { type: 'RESET_RUN' })
      expect(state.running).toBe(false)
      expect(state.taskId).toBeNull()
      expect(state.error).toBeNull()

      state = reducer(state, { type: 'START_RUN', payload: { taskId: 't2', runId: 'r2' } })
      expect(state.running).toBe(true)
      expect(state.taskId).toBe('t2')
    })
  })
})
