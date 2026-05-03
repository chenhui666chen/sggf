import { useEffect, useRef } from 'react'

import type { AudiobookSelectProjectOptions } from './useAudiobookProjectSelectionActions'
import type {
  NavigationType,
  Project,
  TtsModel,
} from './types'
import { getOrCreateAudiobookSessionTabId } from './sessionUtils'
import { detectNavigationType } from './utils'

export const useAudiobookPageRefs = (ttsModel: TtsModel) => {
  const sessionHydratedRef = useRef(false)
  const sessionTabIdRef = useRef<string>(getOrCreateAudiobookSessionTabId())
  const lastSessionTimestampRef = useRef(0)
  const restoredEditorSessionKeyRef = useRef<string | null>(null)
  const restoredPageSessionProjectRef = useRef<number | null>(null)
  const restoredProjectBoundPageSessionKeyRef = useRef<string | null>(null)
  const handledSourceChapterKeyRef = useRef<string | null>(null)
  const skipNextPageSessionPersistRef = useRef(false)
  const dismissedEditorConflictSignatureRef = useRef<string | null>(null)
  const ttsModelRef = useRef<TtsModel>(ttsModel)
  const handleSelectProjectRef = useRef<(project: Project, options?: AudiobookSelectProjectOptions) => Promise<void>>(
    async () => {},
  )
  const navigationTypeRef = useRef<NavigationType>(typeof window === 'undefined' ? null : detectNavigationType())

  useEffect(() => {
    ttsModelRef.current = ttsModel
  }, [ttsModel, ttsModelRef])

  return {
    sessionHydratedRef,
    sessionTabIdRef,
    lastSessionTimestampRef,
    restoredEditorSessionKeyRef,
    restoredPageSessionProjectRef,
    restoredProjectBoundPageSessionKeyRef,
    handledSourceChapterKeyRef,
    skipNextPageSessionPersistRef,
    dismissedEditorConflictSignatureRef,
    ttsModelRef,
    handleSelectProjectRef,
    navigationTypeRef,
  }
}
