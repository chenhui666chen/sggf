import { useState } from 'react'

import type {
  AudiobookEditorSessionState,
  ScriptEditorChapterRef,
  ScriptEditorStateData,
  SmartChunkPreviewResult,
} from './types'

export const useAudiobookScriptEditorState = () => {
  const [scriptEditorDialogOpen, setScriptEditorDialogOpen] = useState(false)
  const [scriptEditorChapter, setScriptEditorChapter] = useState<ScriptEditorChapterRef | null>(null)
  const [scriptEditorData, setScriptEditorData] = useState<ScriptEditorStateData | null>(null)
  const [scriptEditorLoading, setScriptEditorLoading] = useState(false)
  const [smartChunkPreview, setSmartChunkPreview] = useState<SmartChunkPreviewResult | null>(null)
  const [smartChunkPreviewLoading, setSmartChunkPreviewLoading] = useState(false)
  const [editorCrossTabConflict, setEditorCrossTabConflict] = useState<AudiobookEditorSessionState | null>(null)

  return {
    scriptEditorDialogOpen,
    setScriptEditorDialogOpen,
    scriptEditorChapter,
    setScriptEditorChapter,
    scriptEditorData,
    setScriptEditorData,
    scriptEditorLoading,
    setScriptEditorLoading,
    smartChunkPreview,
    setSmartChunkPreview,
    smartChunkPreviewLoading,
    setSmartChunkPreviewLoading,
    editorCrossTabConflict,
    setEditorCrossTabConflict,
  }
}
