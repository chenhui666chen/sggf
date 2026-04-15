import { useCallback, useEffect, useState } from 'react'
import type { DreamweaverEventRecord } from '@/types/dreamweaver'

interface WebSocketState {
  connected: boolean
  reconnecting: boolean
  reconnectAttempts: number
}

interface UseWebSocketReconnectOptions {
  runId: string
  onEvent?: (event: DreamweaverEventRecord) => void
  onStateChange?: (state: WebSocketState) => void
}

export function useWebSocketReconnect(options: UseWebSocketReconnectOptions) {
  const { runId, onStateChange } = options

  const [state, setState] = useState<WebSocketState>({
    connected: false,
    reconnecting: false,
    reconnectAttempts: 0,
  })

  const updateState = useCallback((update: Partial<WebSocketState>) => {
    setState((prev) => {
      const next = { ...prev, ...update }
      onStateChange?.(next)
      return next
    })
  }, [onStateChange])

  useEffect(() => {
    updateState({ connected: true })

    return () => {
      updateState({ connected: false })
    }
  }, [runId, updateState])

  return state
}
