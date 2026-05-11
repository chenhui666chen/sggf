import type { TaskStatus } from './types'

export type TaskProgressStreamEvent = {
  event?: string
  data?: unknown
  timestamp?: string
}

export type TaskProgressStreamConnectionStatus = 'idle' | 'connecting' | 'connected' | 'fallback' | 'closed'

type StreamCapabilityCheck = {
  fetchAvailable: boolean
  abortControllerAvailable: boolean
}

type StreamResponseLike = {
  ok: boolean
  body: ReadableStream<Uint8Array> | null
}

type StreamCloseDecision = {
  cancelled: boolean
  terminalHandled: boolean
  hadConnectedStream: boolean
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value && typeof value === 'object' && !Array.isArray(value))

const getFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

export const consumeSseEventBuffer = (
  buffer: string,
  handleEvent: (event: TaskProgressStreamEvent) => void,
): string => {
  const blocks = buffer.split(/\r?\n\r?\n/)
  const rest = blocks.pop() ?? ''

  for (const block of blocks) {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
      .trim()

    if (!data) {
      continue
    }

    try {
      const parsed = JSON.parse(data) as unknown
      if (isRecord(parsed)) {
        handleEvent({
          event: typeof parsed.event === 'string' ? parsed.event : undefined,
          data: parsed.data,
          timestamp: typeof parsed.timestamp === 'string' ? parsed.timestamp : undefined,
        })
      }
    } catch {
      // 忽略单条无法解析的 SSE 事件，后续轮询兜底会修正状态。
    }
  }

  return rest
}

export const applyTaskProgressStreamPatch = (
  task: TaskStatus | null | undefined,
  event: TaskProgressStreamEvent,
  getNowIso: () => string = () => new Date().toISOString(),
): TaskStatus | null => {
  if (!task || event.event !== 'progress') {
    return null
  }

  const data = isRecord(event.data) ? event.data : {}
  const rawStage = typeof data.stage === 'string' ? data.stage.trim() : ''
  const stage = rawStage || null
  const progress = getFiniteNumber(data.progress)

  if (!stage && progress === null) {
    return null
  }

  const nextProgress = progress === null
    ? task.progress
    : Math.max(task.progress || 0, progress)

  return {
    ...task,
    status: task.status === 'pending' ? 'running' : task.status,
    current_stage: stage ?? task.current_stage,
    progress: nextProgress,
    updated_at: event.timestamp || getNowIso(),
  }
}

export const canStartTaskProgressStream = ({
  fetchAvailable,
  abortControllerAvailable,
}: StreamCapabilityCheck): boolean => fetchAvailable && abortControllerAvailable

export const hasReadableTaskProgressStreamResponse = (
  response: StreamResponseLike,
): response is StreamResponseLike & { ok: true; body: ReadableStream<Uint8Array> } =>
  response.ok && response.body !== null

export const shouldFallbackPollAfterStreamClose = ({
  cancelled,
  terminalHandled,
  hadConnectedStream,
}: StreamCloseDecision): boolean => !cancelled && !terminalHandled && hadConnectedStream
