import { useState, useCallback, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import {
  parseLibraryRole,
  resolveCharacterViewChainPlan,
  formatReferenceRoleLabel,
} from '@/utils/dreamweaverLibraryRole'
import { hasRenderableLibraryImage } from '@/utils/dreamweaverLibraryAssetState'
import type { LibraryAsset } from '@/types/dreamweaver'

interface RegenDialogDeps {
  libraryAssetsByRole: Map<string, LibraryAsset>
  missingRoleSet: Set<string>
  selectedProjectId: number | null
  currentRunId: string | null
}

type RegenerateLibraryAssetFn = (params: Record<string, unknown>) => Promise<string | null>

export function useDreamweaverRegenDialog(deps: RegenDialogDeps) {
  const { libraryAssetsByRole, missingRoleSet, selectedProjectId, currentRunId } = deps
  const { t } = useTranslation()

  const regenerateLibraryAssetRef = useRef<RegenerateLibraryAssetFn>(async () => 'not initialized')
  const setRegenerateLibraryAsset = useCallback((fn: RegenerateLibraryAssetFn) => {
    regenerateLibraryAssetRef.current = fn
  }, [])

  const [regenOpen, setRegenOpen] = useState(false)
  const [regenRole, setRegenRole] = useState<string>('')
  const [regenTitle, setRegenTitle] = useState<string>('')
  const [regenPrompt, setRegenPrompt] = useState<string>('')
  const [regenPromptInitial, setRegenPromptInitial] = useState<string>('')
  const [regenPromptTemplateSnapshot, setRegenPromptTemplateSnapshot] = useState<string>('')
  const [regenImageEditAutoCleared, setRegenImageEditAutoCleared] = useState(false)
  const [regenPromptDirty, setRegenPromptDirty] = useState(false)
  const [regenPreferImageEdit, setRegenPreferImageEdit] = useState(false)
  const [regenSuggesting, setRegenSuggesting] = useState(false)
  const [regenSuggestError, setRegenSuggestError] = useState<string | null>(null)
  const [regenSmartPromptTriggered, setRegenSmartPromptTriggered] = useState(false)
  const [regenSubmitting, setRegenSubmitting] = useState(false)
  const [regenError, setRegenError] = useState<string | null>(null)

  const regenRoleAsset = useMemo(() => {
    const role = String(regenRole || '').trim()
    return libraryAssetsByRole.get(role) || null
  }, [libraryAssetsByRole, regenRole])

  const regenRoleInfo = useMemo(() => parseLibraryRole(regenRole), [regenRole])

  const regenIsDerivedCharacterView = useMemo(
    () => regenRoleInfo.entityType === 'character' && Boolean(regenRoleInfo.view) && regenRoleInfo.view !== 'front',
    [regenRoleInfo],
  )

  const regenViewChainPlan = useMemo(() => resolveCharacterViewChainPlan(regenRole), [regenRole])
  const regenForceImageEdit = regenViewChainPlan.forceImageEdit
  const regenImageBaseRole = regenViewChainPlan.baseRole

  const regenImageBaseAsset = useMemo(() => {
    if (!regenImageBaseRole) return null
    return libraryAssetsByRole.get(regenImageBaseRole) || null
  }, [libraryAssetsByRole, regenImageBaseRole])

  const regenHasRenderableBaseImage = useMemo(
    () => hasRenderableLibraryImage(regenImageBaseAsset, { missingRoleSet }),
    [missingRoleSet, regenImageBaseAsset],
  )

  const regenHasCurrentImage = useMemo(
    () => hasRenderableLibraryImage(regenRoleAsset, { missingRoleSet }),
    [missingRoleSet, regenRoleAsset],
  )

  const regenReferenceRoles = useMemo(() => {
    return (Array.isArray(regenViewChainPlan.referenceRoles) ? regenViewChainPlan.referenceRoles : [])
      .map((item) => String(item || '').trim())
      .filter(Boolean)
  }, [regenViewChainPlan.referenceRoles])

  const regenReadyReferenceRoles = useMemo(() => {
    return regenReferenceRoles.filter((role) => hasRenderableLibraryImage(libraryAssetsByRole.get(role) || null, { missingRoleSet }))
  }, [libraryAssetsByRole, missingRoleSet, regenReferenceRoles])

  const regenMissingReferenceRoles = useMemo(() => {
    return regenReferenceRoles.filter((role) => !hasRenderableLibraryImage(libraryAssetsByRole.get(role) || null, { missingRoleSet }))
  }, [libraryAssetsByRole, missingRoleSet, regenReferenceRoles])

  const regenHasImageBase = useMemo(() => {
    if (regenForceImageEdit) return regenHasRenderableBaseImage
    return regenHasCurrentImage
  }, [regenForceImageEdit, regenHasCurrentImage, regenHasRenderableBaseImage])

  const regenImageEditActive = regenForceImageEdit || (regenPreferImageEdit && regenHasImageBase)

  const regenImageBaseRoleLabel = useMemo(() => {
    return regenImageBaseRole ? formatReferenceRoleLabel(regenImageBaseRole) : t('dreamweaverRun.promptPreviousView')
  }, [regenImageBaseRole, t])

  const regenForceViewChainEditBase = regenForceImageEdit && regenIsDerivedCharacterView && regenSmartPromptTriggered

  const regenAlertBaseLabel = useMemo(() => {
    if (!regenForceImageEdit) return ''
    if (regenForceViewChainEditBase) return regenImageBaseRoleLabel
    if (regenHasCurrentImage) return t('dreamweaverRun.regenImageBaseLabel')
    return regenImageBaseRoleLabel
  }, [regenForceImageEdit, regenForceViewChainEditBase, regenHasCurrentImage, regenImageBaseRoleLabel, t])

  const regenAlertReadyReferenceLabel = useMemo(() => {
    const labels: string[] = []
    const push = (value: string) => {
      const text = String(value || '').trim()
      if (!text) return
      if (!labels.includes(text)) labels.push(text)
    }

    if (!regenForceImageEdit) return ''

    if (regenForceViewChainEditBase) {
      if (regenHasRenderableBaseImage) push(regenImageBaseRoleLabel)
      for (const role of regenReadyReferenceRoles) push(formatReferenceRoleLabel(role))
    } else if (regenHasCurrentImage) {
      push(t('dreamweaverRun.regenImageBaseLabel'))
      for (const role of regenReadyReferenceRoles) push(formatReferenceRoleLabel(role))
    } else {
      if (regenHasRenderableBaseImage) push(regenImageBaseRoleLabel)
      for (const role of regenReadyReferenceRoles) push(formatReferenceRoleLabel(role))
    }

    return labels.join('、')
  }, [
    regenForceImageEdit,
    regenForceViewChainEditBase,
    regenHasCurrentImage,
    regenHasRenderableBaseImage,
    regenImageBaseRoleLabel,
    regenReadyReferenceRoles,
    t,
  ])

  const regenAlertMissingReferenceLabel = useMemo(() => {
    const labels: string[] = []
    const push = (value: string) => {
      const text = String(value || '').trim()
      if (!text) return
      if (!labels.includes(text)) labels.push(text)
    }

    if (!regenForceImageEdit) return ''

    if (regenForceViewChainEditBase) {
      if (!regenHasRenderableBaseImage) push(regenImageBaseRoleLabel)
      for (const role of regenMissingReferenceRoles) push(formatReferenceRoleLabel(role))
    } else if (regenHasCurrentImage) {
      for (const role of regenMissingReferenceRoles) push(formatReferenceRoleLabel(role))
    } else {
      if (!regenHasRenderableBaseImage) push(regenImageBaseRoleLabel)
      for (const role of regenMissingReferenceRoles) push(formatReferenceRoleLabel(role))
    }

    return labels.join('、')
  }, [
    regenForceImageEdit,
    regenForceViewChainEditBase,
    regenHasCurrentImage,
    regenHasRenderableBaseImage,
    regenImageBaseRoleLabel,
    regenMissingReferenceRoles,
  ])

  const regenAlertReadyReferenceCount = useMemo(() => {
    const text = String(regenAlertReadyReferenceLabel || '').trim()
    if (!text) return 0
    return text.split('、').map((s) => s.trim()).filter(Boolean).length
  }, [regenAlertReadyReferenceLabel])

  const regenPromptInputLabel = useMemo(() => {
    if (!(regenImageEditActive && regenImageEditAutoCleared)) return t('dreamweaverRun.promptLabel')
    if (regenForceViewChainEditBase) return t('dreamweaverRun.editReqBasedOnRefImage')
    if (regenHasCurrentImage) return t('dreamweaverRun.editReqBasedOnCurrentImage')
    return t('dreamweaverRun.editReqBasedOnRefImage')
  }, [regenForceViewChainEditBase, regenHasCurrentImage, regenImageEditActive, regenImageEditAutoCleared, t])

  const suggestRegeneratePrompt = useCallback(
    async (options: {
      role: string
      prompt?: string
      mode?: 'template' | 'ai'
      source?: 'auto' | 'manual'
      preferViewChainSeed?: boolean
    }): Promise<string | null> => {
      const role = String(options.role || '').trim()
      if (!selectedProjectId || !role) return null
      setRegenSuggesting(true)
      setRegenSuggestError(null)
      try {
        const res = await apiClient.suggestDreamweaverLibraryPrompt(selectedProjectId, {
          role,
          ...(currentRunId ? { run_id: currentRunId } : {}),
          ...(options.prompt ? { prompt: options.prompt } : {}),
          ...(options.preferViewChainSeed ? { prefer_view_chain_seed: true } : {}),
          mode: options.mode || 'template',
        })
        const nextPrompt = String(res.data?.prompt || '').trim()
        if (nextPrompt) {
          setRegenPrompt(nextPrompt)
          if (options.preferViewChainSeed) setRegenSmartPromptTriggered(true)
          if ((options.source || 'manual') === 'auto') {
            setRegenPromptInitial(nextPrompt)
            setRegenPromptDirty(false)
          } else {
            setRegenPromptDirty(nextPrompt.trim() !== regenPromptInitial.trim())
          }
          return nextPrompt
        }
        return null
      } catch (e: unknown) {
        const message = await extractApiErrorMessage(e, t('dreamweaverRun.suggestPromptFailed'))
        setRegenSuggestError(message)
        return null
      } finally {
        setRegenSuggesting(false)
      }
    },
    [currentRunId, regenPromptInitial, selectedProjectId, t],
  )

  const requestSmartRegeneratePrompt = useCallback(
    (options?: { role?: string; source?: 'auto' | 'manual' }) => {
      const role = String(options?.role || regenRole || '').trim()
      if (!role) return
      const parsed = parseLibraryRole(role)
      const preferViewChainSeed = parsed.entityType === 'character' && Boolean(parsed.view) && parsed.view !== 'front'
      if (preferViewChainSeed) setRegenSmartPromptTriggered(true)
      void suggestRegeneratePrompt({
        role,
        mode: 'template',
        source: options?.source || 'manual',
        preferViewChainSeed,
      })
    },
    [regenRole, suggestRegeneratePrompt],
  )

  const openRegenerateDialogForRole = useCallback((roleInput: string, titleInput?: string, promptInput?: string) => {
    const role = String(roleInput || '').trim()
    if (!role) return
    const roleAsset = libraryAssetsByRole.get(role) || null
    const title = String(titleInput || role).trim() || role
    const prompt = String(promptInput || roleAsset?.meta?.prompt || roleAsset?.meta?.suggested_prompt || '').trim()
    const viewChainPlan = resolveCharacterViewChainPlan(role)
    const hasCurrentImage = hasRenderableLibraryImage(roleAsset, { missingRoleSet })
    const imageEditPref = Boolean(viewChainPlan.forceImageEdit)
    const shouldAutoClearForImageEdit = imageEditPref && hasCurrentImage
    const initialPrompt = shouldAutoClearForImageEdit ? '' : prompt
    setRegenRole(role)
    setRegenTitle(title)
    setRegenPrompt(initialPrompt)
    setRegenPromptInitial(initialPrompt)
    setRegenPromptTemplateSnapshot(prompt)
    setRegenImageEditAutoCleared(shouldAutoClearForImageEdit)
    setRegenPromptDirty(false)
    setRegenPreferImageEdit(imageEditPref)
    setRegenSmartPromptTriggered(false)
    setRegenSuggesting(false)
    setRegenSuggestError(null)
    setRegenError(null)
    setRegenOpen(true)
    if (!hasCurrentImage) {
      requestSmartRegeneratePrompt({ role, source: 'auto' })
    }
  }, [libraryAssetsByRole, missingRoleSet, requestSmartRegeneratePrompt])

  const openRegenerateDialog = useCallback((asset: LibraryAsset) => {
    const role = String(asset.role || '').trim()
    if (!role) return
    const title = String(asset.meta?.entity_name || asset.role || '').trim() || role
    const prompt = String(asset.meta?.prompt || '').trim()
    openRegenerateDialogForRole(role, title, prompt)
  }, [openRegenerateDialogForRole])

  const submitRegenerateDialog = useCallback(async () => {
    const role = String(regenRole || '').trim()
    if (!role || !selectedProjectId) return
    setRegenSubmitting(true)
    setRegenError(null)
    try {
      const promptText = regenPrompt.trim()
      if (regenImageEditActive && regenImageEditAutoCleared && !promptText) {
        setRegenError(t('dreamweaverRun.editReqFillHint'))
        return
      }
      const shouldSendPrompt = regenImageEditActive ? true : Boolean(regenPromptDirty && promptText)
      const err = await regenerateLibraryAssetRef.current({
        role,
        ...(shouldSendPrompt ? { prompt: promptText } : {}),
        run_id: currentRunId || undefined,
        prefer_image_edit: regenForceImageEdit || (regenPreferImageEdit && regenHasImageBase),
        ...(regenForceViewChainEditBase ? { prefer_view_chain_edit_base: true } : {}),
      })
      if (err) {
        setRegenError(err)
        return
      }
      setRegenOpen(false)
    } finally {
      setRegenSubmitting(false)
    }
  }, [regenRole, selectedProjectId, regenPrompt, regenImageEditActive, regenImageEditAutoCleared, regenPromptDirty, currentRunId, regenForceImageEdit, regenPreferImageEdit, regenHasImageBase, regenForceViewChainEditBase, t])

  const toggleRegenImageEditPreference = useCallback(() => {
    if (regenForceImageEdit || !regenHasImageBase) return
    if (regenPreferImageEdit) {
      const restore = String(regenPromptTemplateSnapshot || '').trim()
      setRegenPreferImageEdit(false)
      setRegenImageEditAutoCleared(false)
      setRegenPrompt(restore)
      setRegenPromptInitial(restore)
      setRegenPromptDirty(false)
      return
    }
    const snapshot = String(regenPrompt || regenPromptInitial || regenPromptTemplateSnapshot || '').trim()
    setRegenPromptTemplateSnapshot(snapshot)
    setRegenPreferImageEdit(true)
    if (regenHasCurrentImage) {
      setRegenImageEditAutoCleared(true)
      setRegenPrompt('')
      setRegenPromptInitial('')
    } else {
      setRegenImageEditAutoCleared(false)
    }
    setRegenPromptDirty(false)
  }, [regenForceImageEdit, regenHasImageBase, regenPreferImageEdit, regenPromptTemplateSnapshot, regenPrompt, regenPromptInitial, regenHasCurrentImage])

  const closeRegenDialog = useCallback(() => {
    setRegenOpen(false)
  }, [])

  return {
    regenOpen,
    regenRole,
    regenTitle,
    regenPrompt,
    regenPromptInitial,
    regenPromptTemplateSnapshot,
    regenImageEditAutoCleared,
    regenPromptDirty,
    regenPreferImageEdit,
    regenSuggesting,
    regenSuggestError,
    regenSmartPromptTriggered,
    regenSubmitting,
    regenError,
    regenRoleAsset,
    regenRoleInfo,
    regenIsDerivedCharacterView,
    regenViewChainPlan,
    regenForceImageEdit,
    regenImageBaseRole,
    regenImageBaseAsset,
    regenHasRenderableBaseImage,
    regenHasCurrentImage,
    regenReferenceRoles,
    regenReadyReferenceRoles,
    regenMissingReferenceRoles,
    regenHasImageBase,
    regenImageEditActive,
    regenImageBaseRoleLabel,
    regenForceViewChainEditBase,
    regenAlertBaseLabel,
    regenAlertReadyReferenceLabel,
    regenAlertMissingReferenceLabel,
    regenAlertReadyReferenceCount,
    regenPromptInputLabel,
    setRegenPrompt,
    setRegenPromptDirty,
    setRegenerateLibraryAsset,
    openRegenerateDialog,
    openRegenerateDialogForRole,
    submitRegenerateDialog,
    toggleRegenImageEditPreference,
    closeRegenDialog,
    suggestRegeneratePrompt,
    requestSmartRegeneratePrompt,
  }
}
