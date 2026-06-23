import type { Dispatch, SetStateAction } from 'react'

export type SnackbarSeverity = 'success' | 'info' | 'warning' | 'error'

export interface SnackbarState {
  open: boolean
  message: string
  severity: SnackbarSeverity
}

export type SetSnackbar = Dispatch<SetStateAction<SnackbarState>>

export interface PlayAudioOptions {
  onEnded?: () => void
  startRatio?: number
  startTime?: number
}

export interface ActivateQueuedAudiobookTaskOptions {
  generationMode?: 'full' | 'script_only'
  taskType?: string
  successMessage?: string
}

export type ActivateQueuedAudiobookTask = (
  audiobookProjectId: number,
  jobId: string,
  options?: ActivateQueuedAudiobookTaskOptions,
) => Promise<void>
