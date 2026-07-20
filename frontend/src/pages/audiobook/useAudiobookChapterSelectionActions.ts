import { useCallback, useEffect, useMemo, type Dispatch, type SetStateAction } from 'react'

import {
  normalizeSingleChapterSelection,
  toggleSingleChapterSelection,
} from './chapterSelectionUtils'
import type { Chapter } from './types'

interface UseAudiobookChapterSelectionActionsParams {
  chapters: Chapter[]
  selectedChapters: number[]
  generatedChapterIds: ReadonlySet<number>
  setSelectedChapters: Dispatch<SetStateAction<number[]>>
}

export const useAudiobookChapterSelectionActions = ({
  chapters,
  selectedChapters,
  generatedChapterIds,
  setSelectedChapters,
}: UseAudiobookChapterSelectionActionsParams) => {
  const generatedChapterKey = useMemo(
    () => [...generatedChapterIds].sort((left, right) => left - right).join(','),
    [generatedChapterIds],
  )
  const selectedChapterKey = selectedChapters.join(',')

  useEffect(() => {
    setSelectedChapters((previous) => {
      const normalized = normalizeSingleChapterSelection({
        chapters,
        selectedChapterIds: previous,
        lockedChapterIds: generatedChapterIds,
      })
      return normalized.length === previous.length
        && normalized.every((chapterId, index) => chapterId === previous[index])
        ? previous
        : normalized
    })
  }, [chapters, generatedChapterIds, generatedChapterKey, selectedChapterKey, setSelectedChapters])

  const handleToggleChapter = useCallback((chapterId: number) => {
    setSelectedChapters((previous) => toggleSingleChapterSelection({
      selectedChapterIds: previous,
      chapterId,
      lockedChapterIds: generatedChapterIds,
    }))
  }, [generatedChapterIds, setSelectedChapters])

  return {
    handleToggleChapter,
  }
}
