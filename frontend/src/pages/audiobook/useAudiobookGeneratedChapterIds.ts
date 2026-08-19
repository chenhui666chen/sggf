import { useCallback, useEffect, useMemo, useState } from 'react'

import { apiClient } from '../../services/api'
import { resolveChapterStateById } from './chapterSelectionUtils'
import type { AudiobookProjectDetail, ChapterAudio } from './types'


export const useAudiobookGeneratedChapterIds = ({
  projectId,
  currentChapterAudios,
  currentBatchEngineMode,
  engineMode,
  executionStatusByChapter,
}: {
  projectId: number | null
  currentChapterAudios: ChapterAudio[]
  currentBatchEngineMode?: string | null
  engineMode?: 'legacy_stems' | 'seed_scene'
  executionStatusByChapter?: Record<number, string | null> | null
}) => {
  const [projectHistory, setProjectHistory] = useState<AudiobookProjectDetail[]>([])
  // §3.1：全引擎批次列表（不做 engine_mode 过滤），供点击章节分流定位与
  // 场景编辑器批次切换器使用；与 projectHistory 并行维护，避免重复请求语义
  const [allProjectHistory, setAllProjectHistory] = useState<AudiobookProjectDetail[]>([])

  const loadAllProjects = useCallback(async () => {
    if (!projectId) {
      setAllProjectHistory([])
      return
    }
    try {
      const response = await apiClient.getAudiobookProjectsByProject(projectId, {
        include_chapter_audios: true,
      })
      setAllProjectHistory(Array.isArray(response.data) ? response.data : [])
    } catch {
      setAllProjectHistory([])
    }
  }, [projectId])

  const loadGeneratedChapters = useCallback(async () => {
    if (!projectId) {
      setProjectHistory([])
      return
    }
    try {
      const response = await apiClient.getAudiobookProjectsByProject(projectId, {
        include_chapter_audios: true,
        engine_mode: engineMode,
      })
      setProjectHistory(Array.isArray(response.data) ? response.data : [])
    } catch {
      setProjectHistory([])
    }
  }, [engineMode, projectId])

  useEffect(() => {
    if (!projectId) {
      setProjectHistory([])
      return
    }

    let cancelled = false
    setProjectHistory([])
    const load = async () => {
      try {
        const response = await apiClient.getAudiobookProjectsByProject(projectId, {
          include_chapter_audios: true,
          engine_mode: engineMode,
        })
        if (!cancelled) {
          setProjectHistory(Array.isArray(response.data) ? response.data : [])
        }
      } catch {
        if (!cancelled) {
          setProjectHistory([])
        }
      }
    }

    void load()
    void loadAllProjects()
    return () => {
      cancelled = true
    }
  }, [engineMode, loadAllProjects, projectId])

  const chapterStateById = useMemo(
    () => resolveChapterStateById(
      projectHistory,
      engineMode || 'legacy_stems',
      currentChapterAudios,
      executionStatusByChapter,
      currentBatchEngineMode,
    ),
    [currentBatchEngineMode, currentChapterAudios, engineMode, executionStatusByChapter, projectHistory],
  )

  // 由结构化状态表派生已生成章节集合，向后兼容现有消费方
  const generatedChapterIds = useMemo(
    () => new Set(Object.keys(chapterStateById).map(Number)),
    [chapterStateById],
  )

  return {
    generatedChapterIds,
    chapterStateById,
    allProjectHistory,
    refreshGeneratedChapterIds: loadGeneratedChapters,
    refreshAllProjects: loadAllProjects,
  }
}
