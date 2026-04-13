import { useEffect, useMemo, useState } from 'react'

import { apiClient } from '@/services/api'
import type { Project } from '@/types/project'
import {
  resolveStoryExpansionRecommendation,
  type StoryExpansionRecommendation,
} from '@/utils/storyExpansionRecommendation'

export function useStoryExpansionProjectRecommendation(
  projectId?: string,
): StoryExpansionRecommendation {
  const [projectInfo, setProjectInfo] = useState<Project | null>(null)

  useEffect(() => {
    const numericProjectId = Number.parseInt(projectId || '', 10)
    if (!Number.isFinite(numericProjectId)) {
      setProjectInfo(null)
      return
    }

    let cancelled = false
    setProjectInfo(null)

    void apiClient.getProject(numericProjectId)
      .then((response) => {
        if (!cancelled) {
          setProjectInfo(response.data)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProjectInfo(null)
        }
      })

    return () => {
      cancelled = true
    }
  }, [projectId])

  return useMemo(
    () => resolveStoryExpansionRecommendation(projectInfo),
    [projectInfo],
  )
}
