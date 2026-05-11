import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import type { DreamweaverShotSnapshot } from '@/types/dreamweaver'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { getShotFramePrompt, getShotId, getShotVideoPromptGenerated, getShotVideoPromptOverride } from '@/pages/dreamweaver-run/runPageHelpers'

export type UseDreamweaverPromptEditDialogOptions = {
  currentRunId: string | null
  loadRunSnapshot: () => Promise<void>
}

export type UseDreamweaverPromptEditDialogReturn = {
  promptEditOpen: boolean
  promptEditShot: DreamweaverShotSnapshot | null
  promptEditHead: string
  promptEditTail: string
  promptEditVideo: string
  promptEditSaving: boolean
  promptEditError: string | null
  promptEditGenerated: string | null
  setPromptEditHead: (value: string) => void
  setPromptEditTail: (value: string) => void
  setPromptEditVideo: (value: string) => void
  openPromptEditDialog: (shot: DreamweaverShotSnapshot) => void
  closePromptEditDialog: () => void
  savePromptEdit: () => Promise<void>
  resetPromptEditState: () => void
}

export function useDreamweaverPromptEditDialog(
  options: UseDreamweaverPromptEditDialogOptions,
): UseDreamweaverPromptEditDialogReturn {
  const currentRunIdRef = useRef(options.currentRunId)
  const loadRunSnapshotRef = useRef(options.loadRunSnapshot)

  useEffect(() => {
    currentRunIdRef.current = options.currentRunId
  }, [options.currentRunId])

  useEffect(() => {
    loadRunSnapshotRef.current = options.loadRunSnapshot
  }, [options.loadRunSnapshot])

  const [promptEditOpen, setPromptEditOpen] = useState(false)
  const [promptEditShot, setPromptEditShot] = useState<DreamweaverShotSnapshot | null>(null)
  const [promptEditHead, setPromptEditHead] = useState('')
  const [promptEditTail, setPromptEditTail] = useState('')
  const [promptEditVideo, setPromptEditVideo] = useState('')
  const [promptEditSaving, setPromptEditSaving] = useState(false)
  const [promptEditError, setPromptEditError] = useState<string | null>(null)

  const promptEditGenerated = useMemo(() => getShotVideoPromptGenerated(promptEditShot), [promptEditShot])

  const resetPromptEditState = useCallback(() => {
    setPromptEditOpen(false)
    setPromptEditShot(null)
    setPromptEditHead('')
    setPromptEditTail('')
    setPromptEditVideo('')
    setPromptEditError(null)
  }, [])

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
    if (promptEditSaving) return
    setPromptEditOpen(false)
  }, [promptEditSaving])

  const savePromptEdit = useCallback(async () => {
    const currentRunId = currentRunIdRef.current
    const loadRunSnapshot = loadRunSnapshotRef.current
    if (!currentRunId || !promptEditShot) return
    const shotId = getShotId(promptEditShot)
    if (!shotId) {
      setPromptEditError('缺少 shot_id，无法保存')
      return
    }
    const head = promptEditHead.trim()
    const tail = promptEditTail.trim()
    if (!head || !tail) {
      setPromptEditError('首帧/尾帧提示词不能为空')
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
      await loadRunSnapshot()
      setPromptEditOpen(false)
    } catch (e: unknown) {
      setPromptEditError(await extractApiErrorMessage(e, '提示词保存失败'))
    } finally {
      setPromptEditSaving(false)
    }
  }, [promptEditHead, promptEditShot, promptEditTail, promptEditVideo])

  return {
    promptEditOpen,
    promptEditShot,
    promptEditHead,
    promptEditTail,
    promptEditVideo,
    promptEditSaving,
    promptEditError,
    promptEditGenerated,
    setPromptEditHead,
    setPromptEditTail,
    setPromptEditVideo,
    openPromptEditDialog,
    closePromptEditDialog,
    savePromptEdit,
    resetPromptEditState,
  }
}
