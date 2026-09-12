import { useEffect, type Dispatch, type MutableRefObject, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import {
  buildRestoredAudiobookRouteSessionState,
  clearAudiobookRouteSessionStorage,
  readMatchingAudiobookSession,
  removeStoredSessionWhenProjectMismatch,
  shouldRestoreAudiobookRouteSession,
} from './routeProjectSessionUtils'
import type {
  AudiobookProjectDetail,
  NavigationType,
  Project,
  TaskStatus,
  TtsModel,
} from './types'
import {
  buildPendingTaskStatus,
  isSamePathReferrer,
} from './utils'

type SelectProjectOptions = {
  skipStepReset?: boolean
  preserveSessionState?: boolean
  ttsModelOverride?: TtsModel
  selectedChapterIds?: number[]
}

type SelectProjectFromRef = (project: Project, options?: SelectProjectOptions) => Promise<void>

interface UseAudiobookRouteProjectLoaderParams {
  routeProjectId: number | null
  navigateTo: (path: string) => void
  editorSessionStorageKey: string
  pageSessionStorageKey: string
  navigationTypeRef: MutableRefObject<NavigationType>
  sessionHydratedRef: MutableRefObject<boolean>
  restoredEditorSessionKeyRef: MutableRefObject<string | null>
  restoredPageSessionProjectRef: MutableRefObject<number | null>
  restoredProjectBoundPageSessionKeyRef: MutableRefObject<string | null>
  lastSessionTimestampRef: MutableRefObject<number>
  ttsModelRef: MutableRefObject<TtsModel>
  handleSelectProjectRef: MutableRefObject<SelectProjectFromRef>
  setTtsModel: Dispatch<SetStateAction<TtsModel>>
  setActiveStep: Dispatch<SetStateAction<number>>
  setTaskStatuses: Dispatch<SetStateAction<Record<string, TaskStatus>>>
  setCurrentAudiobookProjectId: Dispatch<SetStateAction<number | null>>
  setAudiobookProject: Dispatch<SetStateAction<AudiobookProjectDetail | null>>
  setCurrentTaskId: Dispatch<SetStateAction<string | null>>
  setGenerating: Dispatch<SetStateAction<boolean>>
  setSnackbar: SetSnackbar
}

export const useAudiobookRouteProjectLoader = ({
  routeProjectId,
  navigateTo,
  editorSessionStorageKey,
  pageSessionStorageKey,
  navigationTypeRef,
  sessionHydratedRef,
  restoredEditorSessionKeyRef,
  restoredPageSessionProjectRef,
  restoredProjectBoundPageSessionKeyRef,
  lastSessionTimestampRef,
  ttsModelRef,
  handleSelectProjectRef,
  setTtsModel,
  setActiveStep,
  setTaskStatuses,
  setCurrentAudiobookProjectId,
  setAudiobookProject,
  setCurrentTaskId,
  setGenerating,
  setSnackbar,
}: UseAudiobookRouteProjectLoaderParams) => {
  const { t } = useTranslation()
  useEffect(() => {
    let cancelled = false

    const loadProjectFromUrl = async () => {
      sessionHydratedRef.current = false
      restoredEditorSessionKeyRef.current = null
      restoredPageSessionProjectRef.current = null
      restoredProjectBoundPageSessionKeyRef.current = null
      lastSessionTimestampRef.current = 0

      if (!routeProjectId) {
        setSnackbar({ open: true, message: t('audiobook.useAudiobookRouteProjectLoader.missingProjectId'), severity: 'error' })
        navigateTo('/audiobook-dashboard')
        return
      }

      const navType = navigationTypeRef.current
      const shouldRestore = shouldRestoreAudiobookRouteSession({
        navigationType: navType,
        samePathReferrer: isSamePathReferrer(),
      })

      if (shouldRestore) {
        removeStoredSessionWhenProjectMismatch({
          storage: sessionStorage,
          storageKey: editorSessionStorageKey,
          routeProjectId,
        })
        removeStoredSessionWhenProjectMismatch({
          storage: sessionStorage,
          storageKey: pageSessionStorageKey,
          routeProjectId,
        })
      } else {
        clearAudiobookRouteSessionStorage({
          localStorageRef: localStorage,
          sessionStorageRef: sessionStorage,
          editorSessionStorageKey,
          pageSessionStorageKey,
        })
      }

      const restoredSessionState = buildRestoredAudiobookRouteSessionState({
        savedSession: shouldRestore
          ? readMatchingAudiobookSession({
              storage: localStorage,
              routeProjectId,
            })
          : null,
        fallbackTtsModel: ttsModelRef.current,
      })
      const {
        savedSession,
        restoredTtsModel,
        restoredSelectedChapterIds,
        restoredActiveTasks,
        restoredTaskId,
        restoredAudiobookProjectId,
        lastSessionTimestamp,
      } = restoredSessionState

      lastSessionTimestampRef.current = lastSessionTimestamp

      if (savedSession && restoredTtsModel !== ttsModelRef.current) {
        setTtsModel(restoredTtsModel)
      }

      try {
        const projectRes = await apiClient.getProject(routeProjectId)
        if (cancelled) return

        const project = projectRes.data as Project
        await handleSelectProjectRef.current(project, {
          skipStepReset: true,
          preserveSessionState: Boolean(savedSession),
          ttsModelOverride: restoredTtsModel,
          selectedChapterIds: restoredSelectedChapterIds,
        })

        if (cancelled || !savedSession) {
          return
        }

        if (typeof savedSession.activeStep === 'number') {
          setActiveStep(savedSession.activeStep)
        }

        if (restoredActiveTasks.length > 0) {
          setTaskStatuses((prev) => {
            const next = { ...prev }
            for (const taskRef of restoredActiveTasks) {
              if (!next[taskRef.taskId]) {
                next[taskRef.taskId] = buildPendingTaskStatus({
                  taskId: taskRef.taskId,
                  audiobookProjectId: taskRef.audiobookProjectId,
                })
              }
            }
            return next
          })
        }

        if (restoredAudiobookProjectId) {
          setCurrentAudiobookProjectId(restoredAudiobookProjectId)
          try {
            const detailRes = await apiClient.getAudiobookProject(restoredAudiobookProjectId)
            if (!cancelled) {
              setAudiobookProject(detailRes.data)
            }
          } catch {
            // 恢复有声书项目失败
          }
        }

        if (!cancelled) {
          setCurrentTaskId(restoredTaskId)
          setGenerating(
            restoredTaskId || restoredActiveTasks.length > 0
              ? (savedSession.generating ?? true)
              : false,
          )
        }
      } catch (error: unknown) {
        const msg = await extractApiErrorMessage(error, t('audiobook.useAudiobookRouteProjectLoader.loadFailed'))
        if (!cancelled) {
          setSnackbar({ open: true, message: msg, severity: 'error' })
          navigateTo('/audiobook-dashboard')
        }
      } finally {
        if (!cancelled) {
          sessionHydratedRef.current = true
        }
      }
    }

    loadProjectFromUrl()

    return () => {
      cancelled = true
    }
  }, [
    editorSessionStorageKey,
    handleSelectProjectRef,
    lastSessionTimestampRef,
    navigateTo,
    navigationTypeRef,
    pageSessionStorageKey,
    restoredEditorSessionKeyRef,
    restoredPageSessionProjectRef,
    restoredProjectBoundPageSessionKeyRef,
    routeProjectId,
    sessionHydratedRef,
    setActiveStep,
    setAudiobookProject,
    setCurrentAudiobookProjectId,
    setCurrentTaskId,
    setGenerating,
    setSnackbar,
    setTaskStatuses,
    setTtsModel,
    ttsModelRef,
    t,
  ])
}
