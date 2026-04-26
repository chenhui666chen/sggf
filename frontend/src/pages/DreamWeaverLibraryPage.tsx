import { useCallback, useEffect, useMemo, useRef, useState, type SyntheticEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Container,
  Divider,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  ImageList,
  ImageListItem,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
  useMediaQuery,
} from '@mui/material'
import { useTheme } from '@mui/material/styles'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import MovieIcon from '@mui/icons-material/Movie'
import RefreshIcon from '@mui/icons-material/Refresh'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { buildDreamWeaverLibraryAssetMetadataContract } from '@/contracts/userAssetMetadataBuilders'
import { buildDreamWeaverLibrarySourcePayload } from '@/contracts/userAssetSourcePayloadBuilders'
import LibraryRegenerateDialog from '@/components/dreamweaver/LibraryRegenerateDialog'
import {
  CHARACTER_VIEW_ORDER,
  characterViewLabel,
  characterViewRole,
  parseLibraryRole,
  type CharacterView,
} from '@/utils/dreamweaverLibraryRole'
import { hasRenderableLibraryImage, resolveLibraryAssetImageState } from '@/utils/dreamweaverLibraryAssetState'
import {
  buildDreamweaverLibrarySourceActivationPlan,
  buildDreamweaverLibrarySourceScrollPlan,
  readUserAssetSourceLibraryAssetId,
} from '@/utils/userAssetSourceNavigation'
import {
  STYLE_PRESETS,
  IMAGE_RATIOS,
  STYLE_PRESET_LABELS,
} from '@/constants/dreamweaver'

type StylePresetValue = typeof STYLE_PRESETS[keyof typeof STYLE_PRESETS]
type ImageRatioValue = typeof IMAGE_RATIOS[keyof typeof IMAGE_RATIOS]

interface LibraryAsset {
  id: number
  role: string
  uri: string
  meta?: Record<string, any>
}

interface LibraryPayload {
  project_id: number
  spec?: Record<string, any>
  review?: Record<string, any>
  assets: LibraryAsset[]
}

interface CollectFeedback {
  type: 'success' | 'error'
  text: string
}

interface CollectState {
  loading: boolean
  feedback: CollectFeedback | null
}

function buildProtectedLibraryAssetUrl(assetId: number): string {
  return `protected://dreamweaver-library/${assetId}`
}

function normalizeStylePresetValue(raw: any): StylePresetValue {
  const text = String(raw || '').trim()
  const allowed = new Set<string>(Object.values(STYLE_PRESETS))
  if (allowed.has(text)) return text as StylePresetValue
  if (text === STYLE_PRESET_LABELS[STYLE_PRESETS.CINEMATIC_REALISTIC]) return STYLE_PRESETS.CINEMATIC_REALISTIC
  if (text === STYLE_PRESET_LABELS[STYLE_PRESETS.ANIME]) return STYLE_PRESETS.ANIME
  if (text === STYLE_PRESET_LABELS[STYLE_PRESETS.INK_WASH]) return STYLE_PRESETS.INK_WASH
  if (text === STYLE_PRESET_LABELS[STYLE_PRESETS.CYBERPUNK]) return STYLE_PRESETS.CYBERPUNK
  return STYLE_PRESETS.CINEMATIC_REALISTIC
}

function normalizeImageRatioValue(raw: any): ImageRatioValue {
  const text = String(raw || '').trim()
  if (text === IMAGE_RATIOS.LANDSCAPE_16_9 || text === IMAGE_RATIOS.PORTRAIT_9_16) {
    return text as ImageRatioValue
  }
  return IMAGE_RATIOS.LANDSCAPE_16_9
}

function ratioToCssAspectRatio(raw: any, fallback: string): string {
  if (typeof raw !== 'string' || !raw.trim()) return fallback
  const parts = raw.split(':').map((p) => Number.parseFloat(p.trim()))
  if (parts.length !== 2 || !Number.isFinite(parts[0]) || !Number.isFinite(parts[1]) || parts[0] <= 0 || parts[1] <= 0) return fallback
  return `${parts[0]} / ${parts[1]}`
}

function assetToCssAspectRatio(asset: LibraryAsset, fallback: string): string {
  const meta = asset?.meta
  const rawWidth = meta?.width
  const rawHeight = meta?.height
  const width = typeof rawWidth === 'number' && Number.isFinite(rawWidth) ? rawWidth : Number.parseInt(String(rawWidth || '0'), 10)
  const height = typeof rawHeight === 'number' && Number.isFinite(rawHeight) ? rawHeight : Number.parseInt(String(rawHeight || '0'), 10)
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) return `${width} / ${height}`
  return ratioToCssAspectRatio(meta?.ratio, fallback)
}

function assetTitle(asset: LibraryAsset): string {
  const name = asset?.meta?.entity_name
  if (typeof name === 'string' && name.trim()) return name.trim()
  return String(asset?.role || '')
}

function isPlaceholderEntityName(value: unknown): boolean {
  const text = String(value || '').trim()
  if (!text) return true
  if (/^[?\s]+$/.test(text)) return true
  const lowered = text.toLowerCase()
  if (lowered === 'unknown' || lowered === 'n/a' || lowered === 'na') return true
  if (text === '未知' || text === '未命名' || text === '角色' || text === '人物' || text === '角色名') return true
  if (text.startsWith('lib_')) return true
  return false
}

type CharacterCard = {
  kind: 'character'
  entityId: number
  title: string
  descriptor: string
  views: Record<CharacterView, LibraryAsset | null>
}

type AssetCard = { kind: 'asset'; asset: LibraryAsset }

type LibraryCard = CharacterCard | AssetCard
type LibraryCardGroupKey = 'character' | 'scene' | 'prop' | 'other'

const LIBRARY_CARD_GROUP_ORDER: ReadonlyArray<{ key: LibraryCardGroupKey; label: string }> = [
  { key: 'character', label: '人物' },
  { key: 'scene', label: '场景' },
  { key: 'prop', label: '道具' },
  { key: 'other', label: '其他' },
]

export default function DreamWeaverLibraryPage() {
  const navigate = useNavigate()
  const params = useParams()
  const [searchParams] = useSearchParams()
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'))
  const isTablet = useMediaQuery(theme.breakpoints.down('md'))
  const cardCols = isMobile ? 1 : isTablet ? 2 : 3

  const projectId = useMemo(() => {
    const raw = String(params.projectId || '').trim()
    const id = Number.parseInt(raw, 10)
    return Number.isFinite(id) && id > 0 ? id : 0
  }, [params.projectId])
  const requestedLibraryAssetId = useMemo(
    () => readUserAssetSourceLibraryAssetId(searchParams),
    [searchParams],
  )

  const [library, setLibrary] = useState<LibraryPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lockedConfig, setLockedConfig] = useState<any>(null)
  const [previews, setPreviews] = useState<Record<number, string>>({})
  const [previewAspectRatios, setPreviewAspectRatios] = useState<Record<number, string>>({})
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
  const previewUrlsRef = useRef<Set<string>>(new Set())
  const handledSourceAssetKeyRef = useRef<string | null>(null)
  const handledSourceAssetScrollKeyRef = useRef<string | null>(null)
  const [characterViewsOpen, setCharacterViewsOpen] = useState(false)
  const [characterViewsEntityId, setCharacterViewsEntityId] = useState<number | null>(null)
  const [collectStates, setCollectStates] = useState<Record<number, CollectState>>({})
  const [showAllCards, setShowAllCards] = useState(false)
  const [selectedRoles, setSelectedRoles] = useState<Set<string>>(new Set())
  const [batchApproving, setBatchApproving] = useState(false)
  const INITIAL_CARD_LIMIT = 20

  const selectedRolesCount = selectedRoles.size
  const hasSelection = selectedRolesCount > 0

  const toggleRoleSelection = useCallback((role: string) => {
    setSelectedRoles((prev) => {
      const next = new Set(prev)
      if (next.has(role)) {
        next.delete(role)
      } else {
        next.add(role)
      }
      return next
    })
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedRoles(new Set())
  }, [])
  const regenRoleInfo = useMemo(() => parseLibraryRole(regenRole), [regenRole])
  const regenIsDerivedCharacterView = useMemo(() => {
    return regenRoleInfo.entityType === 'character' && Boolean(regenRoleInfo.view) && regenRoleInfo.view !== 'front'
  }, [regenRoleInfo])

  const loadLibrary = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    setLibrary(null)
    setLockedConfig(null)
    previewUrlsRef.current.forEach((url) => {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // ignore
      }
    })
    previewUrlsRef.current.clear()
    setPreviews({})
    setPreviewAspectRatios({})
    try {
      const res = await apiClient.getDreamweaverLibrary(projectId)
      const data = (res.data as LibraryPayload) || null
      setLibrary(data)

      try {
        const lockedRes = await apiClient.getDreamweaverProjectLockedConfig(projectId)
        setLockedConfig(lockedRes.data || null)
      } catch {
        setLockedConfig(null)
      }

      const assets = Array.isArray(data?.assets) ? data.assets : []
      const missingRoles = Array.isArray(data?.review?.missing_roles) ? (data!.review!.missing_roles as string[]) : []
      const missingRoleSet = new Set(missingRoles.map((r) => String(r || '').trim()).filter((r) => r))
      const previewEntries = await Promise.all(
        assets
          .filter((asset) => hasRenderableLibraryImage(asset, { missingRoleSet }))
          .map(async (asset) => {
          try {
            const fileRes = await apiClient.getDreamweaverLibraryAssetFile(asset.id)
            const url = URL.createObjectURL(fileRes.data)
            previewUrlsRef.current.add(url)
            return [asset.id, url] as const
          } catch {
            return [asset.id, ''] as const
          }
        }),
      )
      const previewMap: Record<number, string> = {}
      for (const [assetId, url] of previewEntries) {
        if (url) previewMap[assetId] = url
      }
      setPreviews(previewMap)
    } catch (e: any) {
      setError(await extractApiErrorMessage(e, '加载素材库失败'))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void loadLibrary()
  }, [loadLibrary])

  useEffect(() => {
    return () => {
      previewUrlsRef.current.forEach((url) => {
        try {
          URL.revokeObjectURL(url)
        } catch {
          // ignore
        }
      })
      previewUrlsRef.current.clear()
    }
  }, [])

  const approveLibraryRole = useCallback(
    async (role: string, approved: boolean) => {
      const safeRole = String(role || '').trim()
      if (!projectId || !safeRole) return
      setLoading(true)
      setError(null)
      try {
        await apiClient.approveDreamweaverLibrary(projectId, { roles: [safeRole], approved })
        await loadLibrary()
      } catch (e: any) {
        setError(await extractApiErrorMessage(e, '更新审核状态失败'))
      } finally {
        setLoading(false)
      }
    },
    [loadLibrary, projectId],
  )

  const batchApproveLibraryRoles = useCallback(
    async (approved: boolean) => {
      if (!projectId || !selectedRolesCount) return
      setBatchApproving(true)
      setError(null)
      try {
        const roles = Array.from(selectedRoles)
        await apiClient.approveDreamweaverLibrary(projectId, { roles, approved })
        clearSelection()
        await loadLibrary()
      } catch (e: any) {
        setError(await extractApiErrorMessage(e, '批量审核失败'))
      } finally {
        setBatchApproving(false)
      }
    },
    [loadLibrary, projectId, selectedRoles, selectedRolesCount, clearSelection],
  )
  const uploadLibraryAsset = useCallback(
    async (assetId: number, file: File) => {
      if (!projectId) return
      if (!file) return
      if (!String(file.name || '').toLowerCase().endsWith('.png')) {
        setError('仅支持 PNG 文件')
        return
      }
      const maxMb = 10
      if (typeof file.size === 'number' && file.size > maxMb * 1024 * 1024) {
        setError(`文件过大（>${maxMb}MB），请压缩后再上传`)
        return
      }
      setLoading(true)
      setError(null)
      try {
        await apiClient.uploadDreamweaverLibraryAssetFile(assetId, file)
        await loadLibrary()
      } catch (e: any) {
        setError(await extractApiErrorMessage(e, '上传失败'))
      } finally {
        setLoading(false)
      }
    },
    [loadLibrary, projectId],
  )

  const openRegenerateDialogForRole = (roleInput: string, titleInput?: string) => {
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
  }

  const openRegenerateDialog = (asset: LibraryAsset) => {
    openRegenerateDialogForRole(String(asset?.role || '').trim(), String(asset?.meta?.entity_name || asset?.role || '').trim())
  }

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
  const submitRegenerateDialog = async () => {
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
  }

  const assets = Array.isArray(library?.assets) ? library!.assets : []
  const requestedLibraryAsset = useMemo(
    () => (requestedLibraryAssetId ? assets.find((asset) => asset.id === requestedLibraryAssetId) || null : null),
    [assets, requestedLibraryAssetId],
  )
  const requestedCharacterEntityId = useMemo(() => {
    if (!requestedLibraryAsset) return null
    const parsed = parseLibraryRole(String(requestedLibraryAsset.role || '').trim())
    return parsed.entityType === 'character' && parsed.entityId ? parsed.entityId : null
  }, [requestedLibraryAsset])
  const approvedCount = assets.filter((a) => Boolean(a?.meta?.approved)).length
  const missingCount = Array.isArray(library?.review?.missing_roles) ? library!.review!.missing_roles.length : 0
  const unapprovedCount = Array.isArray(library?.review?.unapproved_roles) ? library!.review!.unapproved_roles.length : 0
  const missingRoleSet = useMemo(() => {
    const roles = Array.isArray(library?.review?.missing_roles) ? (library!.review!.missing_roles as string[]) : []
    return new Set(roles.map((r) => String(r || '').trim()).filter((r) => r))
  }, [library])

  const assetsByRole = useMemo(() => {
    const map = new Map<string, LibraryAsset>()
    for (const asset of assets) {
      const role = String(asset?.role || '').trim()
      if (!role) continue
      map.set(role, asset)
    }
    return map
  }, [assets])

  const characterNameById = useMemo(() => {
    const map = new Map<number, string>()
    const remember = (entityIdRaw: unknown, nameRaw: unknown) => {
      const entityId = Number.parseInt(String(entityIdRaw ?? ''), 10)
      const name = String(nameRaw || '').trim()
      if (!Number.isFinite(entityId) || entityId <= 0 || isPlaceholderEntityName(name)) return
      if (!map.has(entityId)) map.set(entityId, name)
    }

    const specCharacters = Array.isArray(library?.spec?.characters) ? (library!.spec!.characters as any[]) : []
    for (const item of specCharacters) {
      remember(item?.entity_id, item?.name)
    }
    for (const asset of assets) {
      const parsed = parseLibraryRole(String(asset?.role || '').trim())
      if (parsed.entityType !== 'character' || !parsed.entityId) continue
      remember(parsed.entityId, asset?.meta?.entity_name)
    }
    return map
  }, [assets, library?.spec])
  const regenRoleAsset = useMemo(() => {
    const role = String(regenRole || '').trim()
    if (!role) return null
    return assetsByRole.get(role) || null
  }, [assetsByRole, regenRole])
  const regenHasCurrentImage = useMemo(
    () => hasRenderableLibraryImage(regenRoleAsset, { missingRoleSet }),
    [missingRoleSet, regenRoleAsset],
  )

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

  const cards = useMemo(() => {
    const spec = library?.spec
    const specCharacters = Array.isArray(spec?.characters) ? (spec!.characters as any[]) : []
    const specScenes = Array.isArray(spec?.scenes) ? (spec!.scenes as any[]) : []
    const specProps = Array.isArray(spec?.props) ? (spec!.props as any[]) : []

    const usedRoles = new Set<string>()
    const out: LibraryCard[] = []

    for (const item of specCharacters) {
      const entityId = Number.parseInt(String(item?.entity_id ?? ''), 10)
      if (!Number.isFinite(entityId) || entityId <= 0) continue
      const rawName = String(item?.name || '').trim()
      const mappedName = characterNameById.get(entityId) || ''
      const title = isPlaceholderEntityName(rawName) ? mappedName || `角色#${entityId}` : rawName
      const descriptor = String(item?.descriptor || '').trim()
      const views = Object.fromEntries(
        CHARACTER_VIEW_ORDER.map((view) => [view, assetsByRole.get(characterViewRole(view, entityId)) || null]),
      ) as Record<CharacterView, LibraryAsset | null>
      for (const viewAsset of Object.values(views)) {
        if (viewAsset?.role) usedRoles.add(String(viewAsset.role).trim())
      }
      out.push({ kind: 'character', entityId, title, descriptor, views })
    }

    const pushRoleIfExists = (role: string) => {
      const asset = assetsByRole.get(role)
      if (!asset) return
      if (usedRoles.has(role)) return
      out.push({ kind: 'asset', asset })
      usedRoles.add(role)
    }

    for (const item of specScenes) {
      const entityId = Number.parseInt(String(item?.entity_id ?? ''), 10)
      if (!Number.isFinite(entityId) || entityId <= 0) continue
      pushRoleIfExists(`lib_scene_card:${entityId}`)
    }
    for (const item of specProps) {
      const entityId = Number.parseInt(String(item?.entity_id ?? ''), 10)
      if (!Number.isFinite(entityId) || entityId <= 0) continue
      pushRoleIfExists(`lib_prop_card:${entityId}`)
    }

    for (const asset of assets) {
      const role = String(asset?.role || '').trim()
      if (!role || usedRoles.has(role)) continue
      const parsed = parseLibraryRole(role)
      // Character assets should be displayed through the merged character card only.
      if (parsed.entityType === 'character') continue
      out.push({ kind: 'asset', asset })
      usedRoles.add(role)
    }
    return out
  }, [assets, assetsByRole, characterNameById, library?.spec])

  const cardGroups = useMemo(() => {
    const groups: Record<LibraryCardGroupKey, LibraryCard[]> = {
      character: [],
      scene: [],
      prop: [],
      other: [],
    }
    for (const card of cards) {
      if (card.kind === 'character') {
        groups.character.push(card)
        continue
      }
      const parsed = parseLibraryRole(card.asset.role)
      if (parsed.entityType === 'character') groups.character.push(card)
      else if (parsed.entityType === 'scene') groups.scene.push(card)
      else if (parsed.entityType === 'prop') groups.prop.push(card)
      else groups.other.push(card)
    }
    const sortKey = (card: LibraryCard) => {
      if (card.kind === 'character') return String(card.title || '').trim()
      return String(card.asset?.meta?.entity_name || card.asset?.role || '').trim()
    }
    ;(Object.keys(groups) as LibraryCardGroupKey[]).forEach((groupKey) => {
      groups[groupKey].sort((a, b) => sortKey(a).localeCompare(sortKey(b), 'zh-CN'))
    })
    return groups
  }, [cards])

  const characterViewsCard = useMemo(() => {
    if (!characterViewsEntityId) return null
    return (
      cards.find((c): c is CharacterCard => c.kind === 'character' && c.entityId === characterViewsEntityId) || null
    )
  }, [cards, characterViewsEntityId])

  const openCharacterViews = (card: CharacterCard) => {
    setCharacterViewsEntityId(card.entityId)
    setCharacterViewsOpen(true)
  }

  const closeCharacterViews = () => {
    if (loading || regenSubmitting) return
    setCharacterViewsOpen(false)
    setCharacterViewsEntityId(null)
  }

  useEffect(() => {
    const activationPlan = buildDreamweaverLibrarySourceActivationPlan({
      projectId,
      requestedLibraryAssetId,
      requestedCharacterEntityId,
      loading,
      handledFocusKey: handledSourceAssetKeyRef.current,
    })
    if (!activationPlan) return
    handledSourceAssetKeyRef.current = activationPlan.focusKey
    setShowAllCards(true)
    if (activationPlan.shouldOpenCharacterViews && activationPlan.characterEntityId) {
      setCharacterViewsEntityId(activationPlan.characterEntityId)
      setCharacterViewsOpen(true)
    }
  }, [loading, projectId, requestedCharacterEntityId, requestedLibraryAssetId])

  useEffect(() => {
    const scrollPlan = buildDreamweaverLibrarySourceScrollPlan({
      projectId,
      requestedLibraryAssetId,
      requestedCharacterEntityId,
      characterViewsOpen,
      loading,
      domAvailable: typeof document !== 'undefined' && typeof window !== 'undefined',
      handledScrollKey: handledSourceAssetScrollKeyRef.current,
    })
    if (!scrollPlan) return

    const target =
      (scrollPlan.targetSelector ? document.querySelector<HTMLElement>(scrollPlan.targetSelector) : null)
      || (scrollPlan.fallbackSelector ? document.querySelector<HTMLElement>(scrollPlan.fallbackSelector) : null)

    if (!target) return
    handledSourceAssetScrollKeyRef.current = scrollPlan.scrollKey
    window.requestAnimationFrame(() => {
      target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })
    })
  }, [characterViewsOpen, loading, projectId, requestedCharacterEntityId, requestedLibraryAssetId])

  const updateCollectState = useCallback((assetId: number, patch: Partial<CollectState>) => {
    setCollectStates((prev) => ({
      ...prev,
      [assetId]: {
        ...prev[assetId],
        loading: false,
        feedback: null,
        ...patch,
      },
    }))
  }, [])

  const getLibraryAssetDisplayTitle = useCallback(
    (asset: LibraryAsset) => {
      const parsed = parseLibraryRole(asset.role)
      const rawEntityName = String(asset?.meta?.entity_name || '').trim()
      const fallbackCharacterName =
        parsed.entityType === 'character' && parsed.entityId
          ? characterNameById.get(parsed.entityId) || `角色#${parsed.entityId}`
          : ''
      const normalizedEntityName = isPlaceholderEntityName(rawEntityName) ? fallbackCharacterName : rawEntityName

      if (parsed.entityType === 'character' && parsed.entityId) {
        if (normalizedEntityName && parsed.view) {
          return `${normalizedEntityName} ${characterViewLabel(parsed.view)}`
        }
        return normalizedEntityName || assetTitle(asset)
      }

      return assetTitle(asset)
    },
    [characterNameById],
  )

  const collectLibraryAsset = useCallback(
    async (asset: LibraryAsset) => {
      const assetId = Number(asset?.id || 0)
      if (!projectId || !assetId) return

      const parsed = parseLibraryRole(asset.role)
      const displayTitle = getLibraryAssetDisplayTitle(asset)
      const descriptor = String(asset?.meta?.descriptor || '').trim()
      const promptPreview = String(asset?.meta?.prompt || asset?.meta?.suggested_prompt || '').trim()
      const approved = Boolean(asset?.meta?.approved)
      const tags = ['dreamweaver', 'library', parsed.entityType || 'other']
      if (parsed.view) {
        tags.push(parsed.view)
      }
      if (approved) {
        tags.push('approved')
      }

      updateCollectState(assetId, { loading: true, feedback: null })

      try {
        await apiClient.createUserAsset({
          project_id: projectId,
          source_module: 'dreamweaver_library',
          asset_kind: 'image',
          asset_class: 'reusable',
          asset_uuid: `dreamweaver-library-${assetId}`,
          storage_mode: 'durable_cloud',
          title: displayTitle,
          description: descriptor || promptPreview || null,
          source_uri: buildProtectedLibraryAssetUrl(assetId),
          preview_uri: buildProtectedLibraryAssetUrl(assetId),
          download_uri: buildProtectedLibraryAssetUrl(assetId),
          model_id:
            String(asset?.meta?.model_id || asset?.meta?.model || asset?.meta?.image_model || '').trim() || null,
          generation_mode: 'library_asset',
          tags,
          metadata_json: buildDreamWeaverLibraryAssetMetadataContract({
            baseMetadata: asset.meta,
            projectId,
            libraryAssetId: assetId,
            libraryRole: asset.role,
            libraryUri: asset.uri,
            entityType: parsed.entityType,
            entityId: parsed.entityId ?? null,
            view: parsed.view ?? null,
            approved,
          }),
          source_payload_json: buildDreamWeaverLibrarySourcePayload({
            projectId,
            assetId,
            role: asset.role,
            uri: asset.uri,
            entityType: parsed.entityType,
            entityId: parsed.entityId ?? null,
            view: parsed.view ?? null,
            approved,
          }),
        })
        updateCollectState(assetId, {
          loading: false,
          feedback: { type: 'success', text: '已收录到用户资产' },
        })
      } catch (collectError) {
        updateCollectState(assetId, {
          loading: false,
          feedback: {
            type: 'error',
            text: await extractApiErrorMessage(collectError, '收录到用户资产失败'),
          },
        })
      }
    },
    [getLibraryAssetDisplayTitle, projectId, updateCollectState],
  )

  const renderLibraryCard = (card: LibraryCard) => {
    if (card.kind === 'character') {
      const viewItems = CHARACTER_VIEW_ORDER.map((view) => {
        const role = characterViewRole(view, card.entityId)
        const asset = card.views[view]
        const state = resolveLibraryAssetImageState(asset, { missingRoleSet })
        const markedMissing = Boolean(role && missingRoleSet.has(role)) || state.markedMissing
        const placeholder = Boolean(asset && state.placeholder && !markedMissing && !state.safetyBlocked)
        return { view, role, asset, state, markedMissing, placeholder }
      })
      const coverItem =
        viewItems.find((item) => item.asset && item.state.hasRenderableImage && previews[item.asset.id]) ||
        viewItems.find((item) => item.asset && item.state.hasRenderableImage) ||
        viewItems.find((item) => Boolean(item.asset)) ||
        null
      const coverAsset = coverItem?.asset || null
      const coverPreview = coverAsset && coverItem?.state.hasRenderableImage ? previews[coverAsset.id] || '' : ''
      const coverAspectRatio = coverAsset
        ? previewAspectRatios[coverAsset.id] || assetToCssAspectRatio(coverAsset, '16 / 9')
        : '16 / 9'
      const totalViews = CHARACTER_VIEW_ORDER.length
      const generatedViews = viewItems.filter((item) => item.state.hasRenderableImage).length
      const missingViews = viewItems.filter((item) => item.markedMissing).length
      const placeholderViews = viewItems.filter((item) => item.placeholder).length
      const blockedViews = viewItems.filter((item) => item.asset && item.state.safetyBlocked).length
      const approvedViews = viewItems.filter((item) => item.asset && item.state.hasRenderableImage && Boolean(item.asset.meta?.approved)).length

      let emptyText = '暂无预览'
      if (generatedViews <= 0) {
        if (missingViews >= totalViews) emptyText = '未生成（缺失）'
        else if (blockedViews > 0) emptyText = '安全拦截'
        else if (placeholderViews > 0) emptyText = '占位图'
        else emptyText = '未生成'
      }

      return (
        <ImageListItem
          key={`character:${card.entityId}`}
          data-library-character-entity-id={card.entityId}
          sx={{
            border:
              requestedCharacterEntityId === card.entityId
                ? '1px solid rgba(255, 215, 64, 0.95)'
                : '1px solid rgba(255,255,255,0.14)',
            borderRadius: 2,
            overflow: 'hidden',
            bgcolor: 'rgba(255,255,255,0.06)',
            breakInside: 'avoid',
            cursor: 'pointer',
            boxShadow:
              requestedCharacterEntityId === card.entityId
                ? '0 0 0 2px rgba(255, 215, 64, 0.18)'
                : 'none',
            '&:hover': { bgcolor: 'rgba(255,255,255,0.08)' },
          }}
          onClick={() => openCharacterViews(card)}
          role="button"
          tabIndex={0}
          aria-label={`查看角色多视角：${card.title}`}
        >
          <Box sx={{ width: '100%', aspectRatio: coverAspectRatio, bgcolor: 'rgba(0,0,0,0.25)', position: 'relative' }}>
            {coverPreview && coverAsset && (
              <Box
                component="img"
                src={coverPreview}
                alt={card.title}
                loading="lazy"
                onLoad={(e: SyntheticEvent<HTMLImageElement>) => {
                  const target = e.currentTarget
                  const width = target.naturalWidth
                  const height = target.naturalHeight
                  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return
                  const cssAspectRatio = `${width} / ${height}`
                  setPreviewAspectRatios((prev) => (prev[coverAsset.id] === cssAspectRatio ? prev : { ...prev, [coverAsset.id]: cssAspectRatio }))
                }}
                sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
              />
            )}
            {!coverPreview && (
              <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'rgba(255,255,255,0.65)', fontSize: 13 }}>
                {emptyText}
              </Box>
            )}
          </Box>
          <Box sx={{ p: 1 }}>
            <Typography variant="caption" sx={{ fontWeight: 700, color: 'rgba(255,255,255,0.92)' }} display="block">
              角色：{card.title}
            </Typography>
            <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap">
              <Chip size="small" label={`六视角：${generatedViews}/${totalViews}`} variant="outlined" />
              <Chip size="small" label={`已通过：${approvedViews}/${totalViews}`} color={approvedViews ? 'success' : 'default'} variant="outlined" />
              {missingViews > 0 && <Chip size="small" label={`缺失：${missingViews}`} color="warning" variant="outlined" />}
              {placeholderViews > 0 && <Chip size="small" label={`占位：${placeholderViews}`} variant="outlined" />}
              {blockedViews > 0 && <Chip size="small" label={`拦截：${blockedViews}`} color="error" variant="outlined" />}
            </Stack>
            {card.descriptor && (
              <Typography
                variant="caption"
                sx={{
                  mt: 0.75,
                  color: 'rgba(255,255,255,0.72)',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {card.descriptor}
              </Typography>
            )}
            <Typography variant="caption" sx={{ display: 'block', mt: 0.75, color: 'rgba(255,255,255,0.55)' }}>
              点击查看六视角详情并生成/替换；已通过的单视角素材可收录到用户中心
            </Typography>
          </Box>
        </ImageListItem>
      )
    }

    const asset = card.asset
    const parsed = parseLibraryRole(asset.role)
    const title = getLibraryAssetDisplayTitle(asset)
    const imageState = resolveLibraryAssetImageState(asset, { missingRoleSet })
    const preview = imageState.hasRenderableImage ? previews[asset.id] : ''
    const aspectRatio = previewAspectRatios[asset.id] || assetToCssAspectRatio(asset, '16 / 9')
    const approved = imageState.hasRenderableImage && Boolean(asset?.meta?.approved)
    const missing = imageState.markedMissing
    const placeholder = imageState.placeholder && !missing && !imageState.safetyBlocked
    const collectState = collectStates[asset.id] || { loading: false, feedback: null }
    const chineseRole =
      parsed.entityType === 'scene'
        ? '场景卡'
        : parsed.entityType === 'prop'
          ? '道具卡'
          : parsed.entityType === 'character' && parsed.view
            ? `角色立绘（${characterViewLabel(parsed.view)}）`
            : ''
    const showRawRole = parsed.entityType === 'unknown'
    const descriptor = String(asset?.meta?.descriptor || '').trim()
    const promptPreview = String(asset?.meta?.prompt || asset?.meta?.suggested_prompt || '').trim()
    const statusText = missing ? '未生成（缺失）' : imageState.safetyBlocked ? '安全拦截' : placeholder ? '占位图' : '暂无预览'

    return (
      <ImageListItem
        key={asset.id}
        data-library-asset-id={asset.id}
        sx={{
          border:
            requestedLibraryAssetId === asset.id
              ? '1px solid rgba(255, 215, 64, 0.95)'
              : '1px solid rgba(255,255,255,0.14)',
          borderRadius: 2,
          overflow: 'hidden',
          bgcolor: 'rgba(255,255,255,0.06)',
          breakInside: 'avoid',
          boxShadow:
            requestedLibraryAssetId === asset.id
              ? '0 0 0 2px rgba(255, 215, 64, 0.18)'
              : 'none',
        }}
      >
        <Box sx={{ width: '100%', aspectRatio, bgcolor: 'rgba(0,0,0,0.25)', position: 'relative' }}>
          <Checkbox
            size="small"
            checked={selectedRoles.has(asset.role)}
            onChange={() => toggleRoleSelection(asset.role)}
            onClick={(e: React.MouseEvent<HTMLButtonElement>) => e.stopPropagation()}
            sx={{
              position: 'absolute',
              top: 4,
              left: 4,
              zIndex: 2,
              bgcolor: 'rgba(0,0,0,0.5)',
              borderRadius: 1,
              '& .MuiSvgIcon-root': { fontSize: 18, color: 'white' },
              '&.Mui-checked .MuiSvgIcon-root': { color: 'primary.main' },
            }}
          />
          {preview && (
            <Box
              component="img"
              src={preview}
              alt={title}
              loading="lazy"
              onLoad={(e: SyntheticEvent<HTMLImageElement>) => {
                const target = e.currentTarget
                const width = target.naturalWidth
                const height = target.naturalHeight
                if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return
                const cssAspectRatio = `${width} / ${height}`
                setPreviewAspectRatios((prev) => (prev[asset.id] === cssAspectRatio ? prev : { ...prev, [asset.id]: cssAspectRatio }))
              }}
              sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            />
          )}
          {!preview && (
            <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'rgba(255,255,255,0.65)', fontSize: 13 }}>
              {statusText}
            </Box>
          )}
        </Box>
        <Box sx={{ p: 1 }}>
          <Typography variant="caption" sx={{ fontWeight: 700, color: 'rgba(255,255,255,0.92)' }} display="block">
            {title}
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap">
            <Chip size="small" label={approved ? '已通过' : '待审核'} color={approved ? 'success' : 'default'} />
            {missing && <Chip size="small" label="缺失" color="warning" variant="outlined" />}
            {placeholder && <Chip size="small" label="占位" variant="outlined" />}
            {imageState.safetyBlocked && <Chip size="small" label="安全拦截" color="error" variant="outlined" />}
            {chineseRole && <Chip size="small" label={chineseRole} variant="outlined" />}
            {showRawRole && (
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.65)', fontFamily: 'monospace' }}>
                {asset.role}
              </Typography>
            )}
          </Stack>
          {(descriptor || promptPreview) && (
            <Box sx={{ mt: 0.75 }}>
              {descriptor && (
                <Typography
                  variant="caption"
                  sx={{
                    color: 'rgba(255,255,255,0.72)',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {descriptor}
                </Typography>
              )}
              {promptPreview && (
                <Typography
                  variant="caption"
                  sx={{
                    mt: 0.5,
                    color: 'rgba(255,255,255,0.55)',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'monospace',
                  }}
                >
                  {promptPreview}
                </Typography>
              )}
            </Box>
          )}
          <Stack direction="row" spacing={1} alignItems="center" mt={1} flexWrap="wrap">
            <Button
              size="small"
              variant="text"
              onClick={() => void approveLibraryRole(asset.role, !approved)}
              disabled={loading || !imageState.hasRenderableImage || imageState.safetyBlocked}
            >
              {approved ? '撤销通过' : '通过'}
            </Button>
            <Button
              size="small"
              variant="outlined"
              component="label"
              startIcon={<UploadFileIcon fontSize="small" />}
              disabled={loading}
            >
              上传替换
              <input
                hidden
                type="file"
                accept="image/png"
                onChange={(e) => {
                  const f = e.target.files && e.target.files[0]
                  e.target.value = ''
                  if (!f) return
                  void uploadLibraryAsset(asset.id, f)
                }}
              />
            </Button>
            <Button
              size="small"
              variant="contained"
              startIcon={<AutoFixHighIcon fontSize="small" />}
              onClick={() => openRegenerateDialog(asset)}
              disabled={loading}
            >
              {imageState.hasRenderableImage ? '重生成' : '生成'}
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={() => void collectLibraryAsset(asset)}
              disabled={loading || collectState.loading || !approved || !imageState.hasRenderableImage || imageState.safetyBlocked}
            >
              {collectState.loading ? '收录中...' : '收录到用户资产'}
            </Button>
          </Stack>
          {collectState.feedback ? (
            <Alert severity={collectState.feedback.type} sx={{ mt: 1, borderRadius: 2 }}>
              {collectState.feedback.text}
            </Alert>
          ) : null}
          {!approved && imageState.hasRenderableImage && !imageState.safetyBlocked ? (
            <Typography variant="caption" sx={{ display: 'block', mt: 0.75, color: 'rgba(255,255,255,0.55)' }}>
              建议先通过审核，再收录到用户中心，避免把未确认素材沉淀为可复用资产。
            </Typography>
          ) : null}
        </Box>
      </ImageListItem>
    )
  }

  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #0b1220 0%, #111827 60%, #0b1220 100%)' }}>
      <Box sx={{ background: 'linear-gradient(135deg, #1976d2 0%, #1565c0 100%)', py: 2.5, px: 2, boxShadow: '0 2px 8px rgba(0,0,0,0.15)' }}>
        <Container maxWidth="lg">
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
            <Stack direction="row" spacing={1.5} alignItems="center">
              <Button
                variant="outlined"
                startIcon={<ArrowBackIcon />}
                onClick={() => navigate('/drama')}
                sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)', '&:hover': { borderColor: 'white', backgroundColor: 'rgba(255,255,255,0.1)' } }}
              >
                返回项目列表
              </Button>
              <Stack direction="row" spacing={1} alignItems="center">
                <MovieIcon sx={{ fontSize: 26, color: 'white' }} />
                <Typography variant="h6" sx={{ color: 'white', fontWeight: 700 }}>
                  项目素材库
                </Typography>
              </Stack>
            </Stack>

            <Stack direction="row" spacing={1} alignItems="center">
              <Button
                variant="outlined"
                startIcon={<RefreshIcon />}
                onClick={loadLibrary}
                disabled={!projectId || loading}
                sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)', '&:hover': { borderColor: 'white', backgroundColor: 'rgba(255,255,255,0.1)' } }}
              >
                刷新
              </Button>
              <Button
                variant="contained"
                color="success"
                onClick={() => projectId && navigate(`/drama/${projectId}`)}
                disabled={!projectId}
              >
                进入生成流程
              </Button>
            </Stack>
          </Box>
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ py: 3 }}>
        {!projectId && <Alert severity="error">projectId 无效</Alert>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {loading && (
          <Box sx={{ mb: 2 }}>
            <LinearProgress />
          </Box>
        )}

        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
          <Chip label={`卡片：${cards.length}`} sx={{ color: 'rgba(255,255,255,0.9)', backgroundColor: 'rgba(255,255,255,0.12)' }} />
          <Chip label={`已通过：${approvedCount}`} color="success" variant="outlined" />
          <Chip label={`缺失：${missingCount}`} color={missingCount ? 'warning' : 'default'} variant="outlined" />
          <Chip label={`待审核：${unapprovedCount}`} color={unapprovedCount ? 'warning' : 'default'} variant="outlined" />
        </Stack>

        {hasSelection && (
          <Paper
            elevation={2}
            sx={{
              mb: 2,
              p: 1.5,
              bgcolor: 'rgba(33, 150, 243, 0.15)',
              border: '1px solid rgba(33, 150, 243, 0.4)',
              borderRadius: 2,
            }}
          >
            <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
              <Chip
                size="small"
                label={`已选择 ${selectedRolesCount} 个素材`}
                color="primary"
                onDelete={clearSelection}
              />
              <Button
                size="small"
                variant="contained"
                color="success"
                disabled={batchApproving || loading}
                onClick={() => void batchApproveLibraryRoles(true)}
              >
                批量通过
              </Button>
              <Button
                size="small"
                variant="outlined"
                color="warning"
                disabled={batchApproving || loading}
                onClick={() => void batchApproveLibraryRoles(false)}
              >
                批量撤销
              </Button>
              <Button size="small" variant="text" onClick={clearSelection}>
                取消选择
              </Button>
            </Stack>
          </Paper>
        )}

        {!loading && !library && !error && (
          <Box sx={{ py: 8, display: 'flex', justifyContent: 'center' }}>
            <CircularProgress />
          </Box>
        )}

        {cards.length ? (
          <Stack spacing={2}>
            {LIBRARY_CARD_GROUP_ORDER.map((group) => {
              const items = cardGroups[group.key] || []
              if (!items.length) return null
              const displayItems = showAllCards ? items : items.slice(0, INITIAL_CARD_LIMIT)
              const hasMore = items.length > INITIAL_CARD_LIMIT
              return (
                <Box key={group.key}>
                  <Stack direction="row" spacing={1} alignItems="center" mb={1} flexWrap="wrap">
                    <Typography variant="subtitle2" sx={{ color: 'rgba(255,255,255,0.95)', fontWeight: 700 }}>
                      {group.label}
                    </Typography>
                    <Chip size="small" label={`数量：${items.length}`} variant="outlined" />
                    {hasMore && !showAllCards && (
                      <Chip
                        size="small"
                        label={`显示更多`}
                        variant="outlined"
                        color="primary"
                        onClick={() => setShowAllCards(true)}
                        sx={{ cursor: 'pointer' }}
                      />
                    )}
                  </Stack>
                  <ImageList variant="standard" cols={cardCols} gap={10} sx={{ m: 0 }}>
                    {displayItems.map(renderLibraryCard)}
                  </ImageList>
                  {hasMore && !showAllCards && (
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => setShowAllCards(true)}
                      sx={{ mt: 1, color: 'rgba(255,255,255,0.85)', borderColor: 'rgba(255,255,255,0.3)' }}
                    >
                      显示全部 {items.length} 个素材
                    </Button>
                  )}
                </Box>
              )
            })}
            {showAllCards && cards.length > INITIAL_CARD_LIMIT && (
              <Button
                size="small"
                variant="outlined"
                onClick={() => setShowAllCards(false)}
                sx={{ color: 'rgba(255,255,255,0.85)', borderColor: 'rgba(255,255,255,0.3)' }}
              >
                收起
              </Button>
            )}
          </Stack>
        ) : (
          !loading && (
            <Typography sx={{ color: 'rgba(255,255,255,0.75)' }}>
              当前项目暂无素材库资产（或尚未生成）。进入生成流程后可在“素材”阶段加载/生成素材库。
            </Typography>
          )
        )}
      </Container>

      <Dialog open={characterViewsOpen} onClose={closeCharacterViews} fullWidth maxWidth="md">
        <DialogTitle>角色多视角：{characterViewsCard?.title || '-'}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
            {characterViewsCard?.descriptor || '暂无角色描述'}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            建议：按六视角顺序生成；非正面视角会优先复用前序视角作为参考，保证角色一致性。
          </Typography>
          <Divider sx={{ my: 2 }} />
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' },
              gap: 1.5,
            }}
          >
            {CHARACTER_VIEW_ORDER.map((view) => {
              const role = characterViewsCard ? characterViewRole(view, characterViewsCard.entityId) : ''
              const asset = characterViewsCard?.views?.[view] || null
              const state = resolveLibraryAssetImageState(asset, { missingRoleSet })
              const hasRenderableImage = state.hasRenderableImage
              const title = asset ? assetTitle(asset) : ''
              const preview = asset && hasRenderableImage ? previews[asset.id] : ''
              const aspectRatio = asset ? previewAspectRatios[asset.id] || assetToCssAspectRatio(asset, '16 / 9') : '16 / 9'
              const approved = hasRenderableImage && Boolean(asset?.meta?.approved)
              const missing = Boolean(role && missingRoleSet.has(role)) || state.markedMissing
              const placeholder = Boolean(asset && state.placeholder && !missing && !state.safetyBlocked)
              const collectState = asset ? collectStates[asset.id] || { loading: false, feedback: null } : { loading: false, feedback: null }
              const stateText = missing ? '未生成（缺失）' : !asset ? '未生成' : state.safetyBlocked ? '安全拦截' : placeholder ? '占位图' : '暂无预览'
              return (
                <Box
                  key={view}
                  data-library-asset-id={asset?.id}
                  sx={{
                    border:
                      requestedLibraryAssetId && asset?.id === requestedLibraryAssetId
                        ? '1px solid rgba(255, 215, 64, 0.95)'
                        : '1px solid rgba(0,0,0,0.12)',
                    borderRadius: 2,
                    overflow: 'hidden',
                    bgcolor: 'rgba(0,0,0,0.02)',
                    boxShadow:
                      requestedLibraryAssetId && asset?.id === requestedLibraryAssetId
                        ? '0 0 0 2px rgba(255, 215, 64, 0.18)'
                        : 'none',
                  }}
                >
                  <Box sx={{ width: '100%', aspectRatio, bgcolor: 'rgba(0,0,0,0.08)', position: 'relative' }}>
                    <Chip
                      size="small"
                      label={characterViewLabel(view)}
                      sx={{
                        position: 'absolute',
                        top: 8,
                        left: 8,
                        bgcolor: 'rgba(0,0,0,0.62)',
                        color: 'white',
                        fontWeight: 700,
                        zIndex: 1,
                      }}
                    />
                    {preview && asset && (
                      <Box
                        component="img"
                        src={preview}
                        alt={`${characterViewLabel(view)}-${title}`}
                        loading="lazy"
                        onLoad={(e: SyntheticEvent<HTMLImageElement>) => {
                          const target = e.currentTarget
                          const width = target.naturalWidth
                          const height = target.naturalHeight
                          if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return
                          const cssAspectRatio = `${width} / ${height}`
                          setPreviewAspectRatios((prev) => (prev[asset.id] === cssAspectRatio ? prev : { ...prev, [asset.id]: cssAspectRatio }))
                        }}
                        sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                      />
                    )}
                    {!preview && (
                      <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'rgba(255,255,255,0.65)', fontSize: 13 }}>
                        {stateText}
                      </Box>
                    )}
                  </Box>
                  <Box sx={{ p: 1 }}>
                    {asset && (
                      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }} display="block">
                        {asset.role}
                      </Typography>
                    )}
                    <Stack direction="row" spacing={1} alignItems="center" mt={0.75} flexWrap="wrap">
                      <Chip size="small" label={approved ? '已通过' : '待审核'} color={approved ? 'success' : 'default'} />
                      {missing && <Chip size="small" label="缺失" color="warning" variant="outlined" />}
                      {placeholder && <Chip size="small" label="占位" variant="outlined" />}
                      {state.safetyBlocked && <Chip size="small" label="安全拦截" color="error" variant="outlined" />}
                    </Stack>
                    <Stack direction="row" spacing={0.75} alignItems="center" mt={1} sx={{ flexWrap: 'nowrap' }}>
                      <Button
                        size="small"
                        variant="text"
                        onClick={() => asset && void approveLibraryRole(asset.role, !approved)}
                        disabled={loading || !asset || !hasRenderableImage || state.safetyBlocked}
                        sx={{ minWidth: 'auto', px: 0.75 }}
                      >
                        {approved ? '撤销通过' : '通过'}
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        component="label"
                        startIcon={<UploadFileIcon fontSize="small" />}
                        disabled={loading || !asset}
                        sx={{
                          minWidth: 'auto',
                          px: 1,
                          '& .MuiButton-startIcon': { mr: 0.5 },
                        }}
                      >
                        上传替换
                        <input
                          hidden
                          type="file"
                          accept="image/png"
                          onChange={(e) => {
                            const f = e.target.files && e.target.files[0]
                            e.target.value = ''
                            if (!f || !asset) return
                            void uploadLibraryAsset(asset.id, f)
                          }}
                        />
                      </Button>
                      <Button
                        size="small"
                        variant="contained"
                        startIcon={<AutoFixHighIcon fontSize="small" />}
                        onClick={() => {
                          if (asset) {
                            openRegenerateDialog(asset)
                            return
                          }
                          if (!role) return
                          const roleTitle = `${characterViewsCard?.title || '角色'}-${characterViewLabel(view)}`
                          openRegenerateDialogForRole(role, roleTitle)
                        }}
                        disabled={loading || !role}
                        sx={{
                          minWidth: 'auto',
                          px: 1,
                          '& .MuiButton-startIcon': { mr: 0.5 },
                        }}
                      >
                        {hasRenderableImage ? '重生成' : '生成'}
                      </Button>
                    </Stack>
                    {asset ? (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => void collectLibraryAsset(asset)}
                        disabled={loading || collectState.loading || !approved || !hasRenderableImage || state.safetyBlocked}
                        sx={{ mt: 1, width: '100%' }}
                      >
                        {collectState.loading ? '收录中...' : '收录到用户资产'}
                      </Button>
                    ) : null}
                    {collectState.feedback ? (
                      <Alert severity={collectState.feedback.type} sx={{ mt: 1, borderRadius: 2 }}>
                        {collectState.feedback.text}
                      </Alert>
                    ) : null}
                  </Box>
                </Box>
              )
            })}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeCharacterViews} disabled={loading || regenSubmitting}>
            关闭
          </Button>
        </DialogActions>
      </Dialog>

      <LibraryRegenerateDialog
        open={regenOpen}
        title={regenTitle || regenRole}
        role={regenRole}
        submitting={regenSubmitting}
        suggesting={regenSuggesting}
        imageEditActive={regenPreferImageEdit}
        forceImageEdit={false}
        hasImageBase={regenHasCurrentImage}
        imageBaseLabel="当前图"
        readyReferenceLabel=""
        readyReferenceCount={0}
        missingReferenceLabel=""
        imageEditAutoCleared={false}
        promptInputLabel="提示词（可选）"
        promptValue={regenPrompt}
        promptPlaceholder={regenPreferImageEdit ? '可以输入要求对原图进行编辑~' : undefined}
        suggestError={regenSuggestError}
        error={regenError}
        submitDisabled={regenSubmitting || regenSuggesting || !regenRole || (regenPreferImageEdit && !regenHasCurrentImage)}
        suggestDisabled={regenSubmitting || regenSuggesting || !regenRole}
        canToggleImageEdit={!(regenSubmitting || regenSuggesting || !regenHasCurrentImage)}
        onClose={() => setRegenOpen(false)}
        onSuggest={() => requestSmartRegeneratePrompt({ source: 'manual', mode: 'template' })}
        onToggleImageEdit={() => {
          setRegenPreferImageEdit((prev) => {
            const next = !prev
            if (next) setRegenPrompt('')
            return next
          })
        }}
        onPromptChange={(value) => setRegenPrompt(value)}
        onSubmit={submitRegenerateDialog}
        showDerivedViewHint={regenIsDerivedCharacterView}
        derivedViewHintText="说明：当前为非正面角色素材。智能生成提示词会按视角链路重建，不沿用当前图提示词。"
        lockedInfoText={lockedConfig?.locked ? '当前项目的风格、比例已锁定，素材库会强制使用锁定配置。' : undefined}
        extraSettings={
          <>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              限制：将覆盖重生成并把该素材标记为“待审核”；上传替换仅支持 PNG。
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1 }}>
              <FormControl fullWidth size="small" disabled={regenSubmitting || regenSuggesting || Boolean(lockedConfig?.locked)}>
                <InputLabel id="library-style-preset-label">风格预设</InputLabel>
                <Select
                  labelId="library-style-preset-label"
                  value={regenStylePreset}
                  label="风格预设"
                  onChange={(e) => setRegenStylePreset(normalizeStylePresetValue(e.target.value))}
                >
                  <MenuItem value="cinematic_realistic">电影写实</MenuItem>
                  <MenuItem value="anime">二次元动画</MenuItem>
                  <MenuItem value="ink_wash">国风水墨</MenuItem>
                  <MenuItem value="cyberpunk">赛博朋克</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" disabled={regenSubmitting || regenSuggesting || Boolean(lockedConfig?.locked)}>
                <InputLabel id="library-image-ratio-label">画幅</InputLabel>
                <Select
                  labelId="library-image-ratio-label"
                  value={regenImageRatio}
                  label="画幅"
                  onChange={(e) => setRegenImageRatio(normalizeImageRatioValue(e.target.value))}
                >
                  <MenuItem value="16:9">横屏 16:9</MenuItem>
                  <MenuItem value="9:16">竖屏 9:16</MenuItem>
                </Select>
              </FormControl>
            </Stack>
          </>
        }
      />
    </Box>
  )
}
