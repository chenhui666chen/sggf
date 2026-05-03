import { useLayoutEffect, type MutableRefObject } from 'react'

import type { Project } from './types'
import type { AudiobookSelectProjectOptions } from './useAudiobookProjectSelectionActions'

type SelectProject = (
  project: Project,
  options?: AudiobookSelectProjectOptions,
) => Promise<void>

export const useAudiobookProjectSelectionRefSync = (
  handleSelectProjectRef: MutableRefObject<SelectProject>,
  handleSelectProject: SelectProject,
) => {
  useLayoutEffect(() => {
    handleSelectProjectRef.current = handleSelectProject
  }, [handleSelectProject, handleSelectProjectRef])
}
