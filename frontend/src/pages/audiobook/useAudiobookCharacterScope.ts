import { useEffect, useMemo, useState } from 'react'

import {
  apiClient,
  extractApiErrorMessage,
  type AudiobookCharacterScopeResponse,
} from '../../services/api'


export const useAudiobookCharacterScope = ({
  projectId,
  selectedChapterIds,
}: {
  projectId: number | null
  selectedChapterIds: number[]
}) => {
  const normalizedChapterIds = useMemo(
    () => [...new Set(selectedChapterIds)].sort((left, right) => left - right),
    [selectedChapterIds],
  )
  const chapterKey = normalizedChapterIds.join(',')
  const [scope, setScope] = useState<AudiobookCharacterScopeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId || normalizedChapterIds.length === 0) {
      setScope(null)
      setLoading(false)
      setError(null)
      return
    }

    let cancelled = false
    setScope(null)
    setLoading(true)
    setError(null)

    const loadScope = async () => {
      try {
        const response = await apiClient.getAudiobookCharacterScope(
          projectId,
          normalizedChapterIds,
        )
        if (!cancelled) {
          setScope(response.data)
        }
      } catch (requestError: unknown) {
        const message = await extractApiErrorMessage(requestError, '章节人物识别失败')
        if (!cancelled) {
          setError(message)
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadScope()
    return () => {
      cancelled = true
    }
  }, [chapterKey, normalizedChapterIds, projectId])

  return {
    characterScope: scope,
    characterScopeLoading: loading,
    characterScopeError: error,
  }
}
