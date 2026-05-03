import { useState } from 'react'

import type {
  AudiobookProjectDetail,
  Chapter,
  Project,
} from './types'

export const useAudiobookProjectState = () => {
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedChapters, setSelectedChapters] = useState<number[]>([])
  const [audiobookProject, setAudiobookProject] = useState<AudiobookProjectDetail | null>(null)
  const selectedProjectId = selectedProject?.id ?? null

  return {
    selectedProject,
    setSelectedProject,
    selectedProjectId,
    chapters,
    setChapters,
    selectedChapters,
    setSelectedChapters,
    audiobookProject,
    setAudiobookProject,
  }
}
