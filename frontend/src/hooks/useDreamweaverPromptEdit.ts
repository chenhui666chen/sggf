import { useState, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, extractApiErrorMessage } from '../services/api'
import type { DreamweaverShotSnapshot } from '../types/dreamweaver'

function getShotFramePrompt(frame: unknown): string {
  if (!frame || typeof frame !== 'object' || Array.isArray(frame)) return ''
  const rec = frame as Record<string, unknown>
  return String(rec.prompt ?? rec.suggested_prompt ?? '')
}

function getShotVideoPromptOverride(shot: DreamweaverShotSnapshot): string {
  if (!shot || typeof shot !== 'object') return ''
  const meta = (shot as Record<string, unknown>).meta
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return ''
  return String((meta as Record<string, unknown>).video_prompt_override ?? '')
}

function getShotId(shot: DreamweaverShotSnapshot): string {
  if (!shot || typeof shot !== 'object') return ''
  return String((shot as Record<string, unknown>).shot_id ?? '')
}

function getShotVideoPromptGenerated(shot: DreamweaverShotSnapshot | null): string | null {
  if (!shot || typeof shot !== 'object') return null
  const meta = (shot as Record<string, unknown>).meta
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null
  return (meta as Record<string, unknown>).video_prompt_generated as string | null ?? null
}

export interface UseDreamweaverPromptEditParams {
  getCurrentRunId: () => string | null
  onLoadSnapshot: () => Promise<void>
}

export interface UseDreamweaverPromptEditReturn {
  promptEditOpen: boolean
  promptEditShot: DreamweaverShotSnapshot | null
  promptEditHead: string
  promptEditTail: string
  promptEditVideo: string
  promptEditSaving: boolean
  promptEditError: string | null
  promptEditGenerated: string | null
  openPromptEditDialog: (shot: DreamweaverShotSnapshot) => void
  savePromptEdit: () => Promise<void>
  closePromptEditDialog: () => void
  setPromptEditHead: (v: string) => void
  setPromptEditTail: (v: string) => void
  setPromptEditVideo: (v: string) => void
}

export function useDreamweaverPromptEdit(
  params: UseDreamweaverPromptEditParams,
): UseDreamweaverPromptEditReturn {
  const { getCurrentRunId, onLoadSnapshot } = params
  const { t } = useTranslation()

  const [promptEditOpen, setPromptEditOpen] = useState(false)
  const [promptEditShot, setPromptEditShot] = useState<DreamweaverShotSnapshot | null>(null)
  const [promptEditHead, setPromptEditHead] = useState('')
  const [promptEditTail, setPromptEditTail] = useState('')
  const [promptEditVideo, setPromptEditVideo] = useState('')
  const [promptEditSaving, setPromptEditSaving] = useState(false)
  const [promptEditError, setPromptEditError] = useState<string | null>(null)

  const promptEditGenerated = useMemo(
    () => getShotVideoPromptGenerated(promptEditShot),
    [promptEditShot],
  )

  const openPromptEditDialog = useCallback((shot: DreamweaverShotSnapshot) => {
    const head = getShotFramePrompt(shot.head_frame)
    const tail = getShotFramePrompt(shot.tail_frame)
    const videoOverride = getShotVideoPromptOverride(shot)
    setPromptEditShot(shot)
    setPromptEditHead(head)
    setPromptEditTail(tail)
    setPromptEditVideo(videoOverride)
    setPromptEditError(null)
    setPromptEditOpen(true)
  }, [])

  const closePromptEditDialog = useCallback(() => {
    setPromptEditOpen(false)
    setPromptEditShot(null)
    setPromptEditHead('')
    setPromptEditTail('')
    setPromptEditVideo('')
    setPromptEditError(null)
  }, [])

  const savePromptEdit = useCallback(async () => {
    const currentRunId = getCurrentRunId()
    if (!currentRunId || !promptEditShot) return
    const shotId = getShotId(promptEditShot)
    if (!shotId) {
      setPromptEditError(t('dreamweaverRun.errorMissingShotIdSave'))
      return
    }
    const head = promptEditHead.trim()
    const tail = promptEditTail.trim()
    if (!head || !tail) {
      setPromptEditError(t('dreamweaverRun.errorFramePromptEmpty'))
      return
    }

    const originHead = getShotFramePrompt(promptEditShot.head_frame)
    const originTail = getShotFramePrompt(promptEditShot.tail_frame)
    const originVideo = getShotVideoPromptOverride(promptEditShot)
    const nextVideo = promptEditVideo.trim()

    const tasks: Promise<any>[] = []
    if (head !== originHead) {
      tasks.push(apiClient.updateDreamweaverRunShotFramePrompt(currentRunId, shotId, 'head', head))
    }
    if (tail !== originTail) {
      tasks.push(apiClient.updateDreamweaverRunShotFramePrompt(currentRunId, shotId, 'tail', tail))
    }
    if (nextVideo !== originVideo) {
      tasks.push(apiClient.updateDreamweaverRunShotVideoPrompt(currentRunId, shotId, nextVideo))
    }
    if (!tasks.length) {
      setPromptEditOpen(false)
      return
    }

    setPromptEditSaving(true)
    setPromptEditError(null)
    try {
      await Promise.all(tasks)
      await onLoadSnapshot()
      setPromptEditOpen(false)
    } catch (e: unknown) {
      setPromptEditError(await extractApiErrorMessage(e, t('dreamweaverRun.errorSavePromptFailed')))
    } finally {
      setPromptEditSaving(false)
    }
  }, [getCurrentRunId, onLoadSnapshot, promptEditShot, promptEditHead, promptEditTail, promptEditVideo, t])

  return {
    promptEditOpen,
    promptEditShot,
    promptEditHead,
    promptEditTail,
    promptEditVideo,
    promptEditSaving,
    promptEditError,
    promptEditGenerated,
    openPromptEditDialog,
    savePromptEdit,
    closePromptEditDialog,
    setPromptEditHead,
    setPromptEditTail,
    setPromptEditVideo,
  }
}
