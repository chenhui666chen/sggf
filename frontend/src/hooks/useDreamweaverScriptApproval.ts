import { useState, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { DreamweaverScriptEntities } from '@/types/dreamweaver'
import { apiClient, extractApiErrorMessage } from '@/services/api'

interface ScriptGeneration {
  mode?: string | null
  model?: string | null
  error?: string | null
  [key: string]: unknown
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function toDreamweaverScriptEntities(value: unknown): DreamweaverScriptEntities | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const toBucket = (bucket: unknown): DreamweaverScriptEntities['characters'] => {
    if (!Array.isArray(bucket)) return []
    return bucket.filter(
      (item): item is DreamweaverScriptEntities['characters'][number] =>
        Boolean(item) && typeof item === 'object' && !Array.isArray(item),
    )
  }
  return {
    characters: toBucket(record.characters),
    scenes: toBucket(record.scenes),
    props: toBucket(record.props),
  }
}

export function useDreamweaverScriptApproval() {
  const { t } = useTranslation()
  const [scriptLoading, setScriptLoading] = useState(false)
  const [scriptError, setScriptError] = useState<string | null>(null)
  const [scriptText, setScriptText] = useState<string>('')
  const [scriptSavedText, setScriptSavedText] = useState<string>('')
  const [scriptApproved, setScriptApproved] = useState(false)
  const [scriptRequiresReview, setScriptRequiresReview] = useState(true)
  const [scriptEntities, setScriptEntities] = useState<DreamweaverScriptEntities | null>(null)
  const [scriptGeneration, setScriptGeneration] = useState<ScriptGeneration | null>(null)

  const autoLoadedScriptRunIdRef = useRef<string | null>(null)

  const scriptDirty = scriptText !== scriptSavedText

  const resetScriptState = useCallback(() => {
    setScriptError(null)
    setScriptText('')
    setScriptSavedText('')
    setScriptApproved(false)
    setScriptRequiresReview(true)
    setScriptEntities(null)
    setScriptGeneration(null)
    autoLoadedScriptRunIdRef.current = null
  }, [])

  const loadScript = useCallback(async (currentRunId: string) => {
    if (!currentRunId) return
    setScriptLoading(true)
    setScriptError(null)
    try {
      const res = await apiClient.getDreamweaverRunScript(currentRunId)
      const data = asObject(res.data) || {}
      const text = typeof data?.script_text === 'string' ? data.script_text : ''
      const scriptReview = asObject(data?.script_review)
      const sg =
        data?.script_generation && typeof data.script_generation === 'object' && !Array.isArray(data.script_generation)
          ? (data.script_generation as ScriptGeneration)
          : null
      setScriptText(text)
      setScriptSavedText(text)
      setScriptApproved(Boolean(scriptReview?.approved))
      setScriptRequiresReview(Boolean(data?.script_requires_review))
      setScriptEntities(toDreamweaverScriptEntities(data?.script_entities))
      setScriptGeneration(sg)
    } catch (e: unknown) {
      setScriptError(await extractApiErrorMessage(e, t('dreamweaverRun.loadScriptFailed')))
    } finally {
      setScriptLoading(false)
    }
  }, [t])

  const saveScript = useCallback(async (currentRunId: string) => {
    if (!currentRunId) return
    if (!scriptText.trim()) {
      setScriptError(t('dreamweaverRun.scriptEmpty'))
      return
    }
    setScriptLoading(true)
    setScriptError(null)
    try {
      await apiClient.updateDreamweaverRunScript(currentRunId, { script_text: scriptText })
      await loadScript(currentRunId)
    } catch (e: unknown) {
      setScriptError(await extractApiErrorMessage(e, t('dreamweaverRun.saveScriptFailed')))
    } finally {
      setScriptLoading(false)
    }
  }, [scriptText, loadScript, t])

  const approveScript = useCallback(async (currentRunId: string, approved: boolean) => {
    if (!currentRunId) return
    setScriptLoading(true)
    setScriptError(null)
    try {
      await apiClient.approveDreamweaverRunScript(currentRunId, { approved })
      await loadScript(currentRunId)
    } catch (e: unknown) {
      setScriptError(await extractApiErrorMessage(e, t('dreamweaverRun.updateScriptApprovalFailed')))
    } finally {
      setScriptLoading(false)
    }
  }, [loadScript, t])

  const autoLoadIfNeeded = useCallback((currentRunId: string | null, waitingScriptApproval: boolean) => {
    if (!waitingScriptApproval) return
    if (!currentRunId) return
    if (scriptLoading) return
    if (scriptText.trim()) return
    if (autoLoadedScriptRunIdRef.current === currentRunId) return
    autoLoadedScriptRunIdRef.current = currentRunId
    void loadScript(currentRunId)
  }, [scriptLoading, scriptText, loadScript])

  return {
    scriptLoading,
    scriptError,
    scriptText,
    scriptSavedText,
    scriptApproved,
    scriptRequiresReview,
    scriptEntities,
    scriptGeneration,
    scriptDirty,
    setScriptText,
    setScriptError,
    resetScriptState,
    loadScript,
    saveScript,
    approveScript,
    autoLoadIfNeeded,
  }
}
