import { useEffect, useState } from 'react'

import {
  workflowWebSocket,
  type AudiobookProgressData,
} from '../../services/websocket'

interface UseAudiobookRealtimeProgressParams {
  audiobookProjectId: number | null
  taskId: string | null
}

export const useAudiobookRealtimeProgress = ({
  audiobookProjectId,
  taskId,
}: UseAudiobookRealtimeProgressParams): AudiobookProgressData | null => {
  const [latestProgress, setLatestProgress] = useState<AudiobookProgressData | null>(null)

  useEffect(() => {
    setLatestProgress(null)
    if (!audiobookProjectId || !taskId) {
      return
    }

    let cancelled = false
    let unsubscribe: () => void = () => undefined

    void workflowWebSocket.connect().then(() => {
      if (cancelled) {
        return
      }
      unsubscribe = workflowWebSocket.onAudiobookProgress((event) => {
        if (event.audiobook_project_id === audiobookProjectId) {
          setLatestProgress(event)
        }
      })
      workflowWebSocket.joinAudiobook(audiobookProjectId)
    }).catch(() => {
      // 任务轮询仍会继续工作，实时进度连接失败不阻断生成流程。
    })

    return () => {
      cancelled = true
      unsubscribe()
      workflowWebSocket.leaveAudiobook(audiobookProjectId)
    }
  }, [audiobookProjectId, taskId])

  return latestProgress
}
