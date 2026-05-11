import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { parseLibraryRole, characterViewLabel, characterViewRole } from '@/utils/dreamweaverLibraryRole'
import { hasRenderableLibraryImage } from '@/utils/dreamweaverLibraryAssetState'
import { STYLE_PRESETS, IMAGE_RATIOS } from '@/constants/dreamweaver'
import type { LibraryAsset, LibraryPayload, StylePresetValue, ImageRatioValue } from './libraryPageUtils'
import { normalizeStylePresetValue, normalizeImageRatioValue, isPlaceholderEntityName } from './libraryPageUtils'

export interface UseLibraryRegenDialogParams {
  projectId: number
  loading: boolean
  lockedConfig: any
  assetsByRole: Map<string, LibraryAsset>
  characterNameById: Map<number, string>
  missingRoleSet: Set<string>
  loadLibrary: () => Promise<void>
}

export interface UseLibraryRegenDialogReturn {
  regenOpen: boolean
  regenRole: string
  regenTitle: string
  regenPrompt: string
  regenPreferImageEdit: boolean
  regenStylePreset: StylePresetValue
  regenImageRatio: ImageRatioValue
  regenSubmitting: boolean
  regenSuggesting: boolean
  regenSuggestError: string | null
  regenError: string | null
  regenRoleInfo: ReturnType<typeof parseLibraryRole>
  regenIsDerivedCharacterView: boolean
  regenHasCurrentImage: boolean
  regenRoleAsset: LibraryAsset | null
  openRegenerateDialog: (asset: LibraryAsset) => void
  openRegenerateDialogForRole: (roleInput: string, titleInput?: string) => void
  setRegenOpen: (v: boolean) => void
  setRegenPrompt: (v: string) => void
  setRegenPreferImageEdit: (v: boolean | ((prev: boolean) => boolean)) => void
  setRegenStylePreset: (v: StylePresetValue) => void
  setRegenImageRatio: (v: ImageRatioValue) => void
  submitRegenerateDialog: () => Promise<void>
  requestSmartRegeneratePrompt: (options?: { role?: string; source?: 'auto' | 'manual'; mode?: 'template' | 'ai'; prompt?: string }) => void
}

export function useLibraryRegenDialog(params: UseLibraryRegenDialogParams): UseLibraryRegenDialogReturn {
  const { projectId, loading, lockedConfig, assetsByRole, characterNameById, missingRoleSet, loadLibrary } = params

  const [regenOpen, setRegenOpen] = useState(false)
  const [regenRole, setRegenRole] = useState('')
  const [regenTitle, setRegenTitle] = useState('')
  const [regenPrompt, setRegenPrompt] = useState('')
  const [regenPreferImageEdit, setRegenPreferImageEdit] = useState(false)
  const [regenStylePreset, setRegenStylePreset] = useState<StylePresetValue>(STYLE_PRESETS.CINEMATIC_REALISTIC)
  const [regenImageRatio, setRegenImageRatio] = useState<ImageRatioValue>(IMAGE_RATIOS.LANDSCAPE_16_9)
  const [regenSubmitting, setRegenSubmitting] = useState(false)
  const [regenSuggesting, setRegenSuggesting] = useState(false)
  const [regenSuggestError, setRegenSuggestError] = useState<string | null>(null)
  const [regenError, setRegenError] = useState<string | null>(null)
  const regenSuggestRequestIdRef = useRef(0)

  const regenRoleInfo = useMemo(() => parseLibraryRole(regenRole), [regenRole])
  const regenIsDerivedCharacterView = useMemo(() => {
    return regenRoleInfo.entityType === 'character' && Boolean(regenRoleInfo.view) && regenRoleInfo.view !== 'front'
  }, [regenRoleInfo])

  const regenRoleAsset = useMemo(() => {
    const role = String(regenRole || '').trim()
    if (!role) return null
    return assetsByRole.get(role) || null
  }, [assetsByRole, regenRole])

  const regenHasCurrentImage = useMemo(
    () => hasRenderableLibraryImage(regenRoleAsset, { missingRoleSet }),
    [missingRoleSet, regenRoleAsset],
  )

  const suggestPrompt = useCallback(
    async (options: { mode?: 'template' | 'ai'; source?: 'auto' | 'manual'; prompt?: string }): Promise<string | null> => {
      const role = String(regenRole || '').trim()
      if (!projectId || !role) return null
      const requestId = regenSuggestRequestIdRef.current + 1
      regenSuggestRequestIdRef.current = requestId
      setRegenSuggesting(true)
      setRegenSuggestError(null)
      try {
        const parsed = parseLibraryRole(role)
        const preferViewChainSeed = parsed.entityType === 'character' && Boolean(parsed.view) && parsed.view !== 'front'
        const res = await apiClient.suggestDreamweaverLibraryPrompt(projectId, {
          role,
          ...(options.prompt ? { prompt: options.prompt } : {}),
          style_preset: regenStylePreset,
          image_ratio: regenImageRatio,
          ...(preferViewChainSeed ? { prefer_view_chain_seed: true } : {}),
          mode: options.mode || 'template',
        })
        if (regenSuggestRequestIdRef.current !== requestId) return null
        const nextPrompt = String(res.data?.prompt || '').trim()
        if (nextPrompt) {
          setRegenPrompt(nextPrompt)
          return nextPrompt
        }
        return null
      } catch (e: any) {
        if (regenSuggestRequestIdRef.current !== requestId) return null
        setRegenSuggestError(await extractApiErrorMessage(e, '生成提示词失败'))
        return null
      } finally {
        if (regenSuggestRequestIdRef.current === requestId) {
          setRegenSuggesting(false)
        }
      }
    },
    [projectId, regenImageRatio, regenRole, regenStylePreset],
  )

  const requestSmartRegeneratePrompt = useCallback(
    (options?: { role?: string; source?: 'auto' | 'manual'; mode?: 'template' | 'ai'; prompt?: string }) => {
      const role = String(options?.role || regenRole || '').trim()
      if (!role) return
      void suggestPrompt({
        mode: options?.mode || 'template',
        source: options?.source || 'manual',
        prompt: options?.prompt,
      })
    },
    [regenRole, suggestPrompt],
  )

  useEffect(() => {
    if (regenOpen) return
    regenSuggestRequestIdRef.current += 1
    setRegenSuggesting(false)
  }, [regenOpen])

  useEffect(() => {
    if (!regenOpen) return
    if (!projectId) return
    if (!String(regenRole || '').trim()) return
    if (regenHasCurrentImage) return
    void requestSmartRegeneratePrompt({ source: 'auto', mode: 'template' })
  }, [
    projectId,
    regenHasCurrentImage,
    regenImageRatio,
    regenOpen,
    regenRole,
    regenStylePreset,
    requestSmartRegeneratePrompt,
  ])

  const openRegenerateDialogForRole = useCallback((roleInput: string, titleInput?: string) => {
    const role = String(roleInput || '').trim()
    if (!role) return
    const roleAsset = assetsByRole.get(role) || null
    const parsed = parseLibraryRole(role)
    const rawTitle = String(titleInput || roleAsset?.meta?.entity_name || roleAsset?.role || role).trim()
    let title = rawTitle || role
    if (parsed.entityType === 'character' && parsed.entityId) {
      const mapped = characterNameById.get(parsed.entityId) || `角色#${parsed.entityId}`
      if (isPlaceholderEntityName(title) || title === role || title.startsWith('lib_character_portrait')) {
        title = mapped
      }
      if (parsed.view) {
        const viewLabel = characterViewLabel(parsed.view)
        if (!title.includes(viewLabel)) title = `${title} ${viewLabel}`
      }
    }
    const prompt = String(roleAsset?.meta?.prompt || roleAsset?.meta?.suggested_prompt || '').trim()
    const locked = Boolean(lockedConfig?.locked)
    const stylePreset = locked
      ? normalizeStylePresetValue(lockedConfig?.style_preset)
      : normalizeStylePresetValue(roleAsset?.meta?.style_preset)
    const ratio = locked ? normalizeImageRatioValue(lockedConfig?.image_ratio) : normalizeImageRatioValue(roleAsset?.meta?.ratio)
    setRegenRole(role)
    setRegenTitle(title)
    setRegenPrompt(prompt)
    setRegenPreferImageEdit(false)
    setRegenStylePreset(stylePreset)
    setRegenImageRatio(ratio)
    setRegenError(null)
    setRegenSuggestError(null)
    setRegenOpen(true)
  }, [assetsByRole, characterNameById, lockedConfig])

  const openRegenerateDialog = useCallback((asset: LibraryAsset) => {
    openRegenerateDialogForRole(
      String(asset?.role || '').trim(),
      String(asset?.meta?.entity_name || asset?.role || '').trim(),
    )
  }, [openRegenerateDialogForRole])

  const submitRegenerateDialog = useCallback(async () => {
    const role = String(regenRole || '').trim()
    if (!projectId || !role) return
    setRegenSubmitting(true)
    setRegenError(null)
    try {
      const trimmedPrompt = regenPrompt.trim()
      await apiClient.regenerateDreamweaverLibraryAsset(projectId, {
        role,
        ...(trimmedPrompt ? { prompt: trimmedPrompt } : {}),
        style_preset: regenStylePreset,
        image_ratio: regenImageRatio,
        ...(regenPreferImageEdit && trimmedPrompt ? { prefer_image_edit: true } : {}),
      })
      await loadLibrary()
      setRegenOpen(false)
    } catch (e: any) {
      setRegenError(await extractApiErrorMessage(e, '重生成失败'))
    } finally {
      setRegenSubmitting(false)
    }
  }, [loadLibrary, projectId, regenImageRatio, regenPreferImageEdit, regenPrompt, regenRole, regenStylePreset])

  return {
    regenOpen,
    regenRole,
    regenTitle,
    regenPrompt,
    regenPreferImageEdit,
    regenStylePreset,
    regenImageRatio,
    regenSubmitting,
    regenSuggesting,
    regenSuggestError,
    regenError,
    regenRoleInfo,
    regenIsDerivedCharacterView,
    regenHasCurrentImage,
    regenRoleAsset,
    openRegenerateDialog,
    openRegenerateDialogForRole,
    setRegenOpen,
    setRegenPrompt,
    setRegenPreferImageEdit,
    setRegenStylePreset,
    setRegenImageRatio,
    submitRegenerateDialog,
    requestSmartRegeneratePrompt,
  }
}
