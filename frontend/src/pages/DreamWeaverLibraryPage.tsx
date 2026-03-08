import { useCallback, useEffect, useMemo, useState, type SyntheticEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
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
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import MovieIcon from '@mui/icons-material/Movie'
import RefreshIcon from '@mui/icons-material/Refresh'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import { apiClient, extractApiErrorMessage } from '@/services/api'

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

function normalizeStylePresetValue(raw: any): string {
  const text = String(raw || '').trim()
  const allowed = new Set(['cinematic_realistic', 'anime', 'ink_wash', 'cyberpunk'])
  if (allowed.has(text)) return text
  if (text === '电影写实') return 'cinematic_realistic'
  if (text === '二次元动画') return 'anime'
  if (text === '国风水墨') return 'ink_wash'
  if (text === '赛博朋克') return 'cyberpunk'
  return 'cinematic_realistic'
}

function normalizeImageRatioValue(raw: any): string {
  const text = String(raw || '').trim()
  if (text === '16:9' || text === '9:16') return text
  return '16:9'
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

type CharacterView = 'front' | 'side' | 'back'

type CharacterCard = {
  kind: 'character'
  entityId: number
  title: string
  descriptor: string
  views: Record<CharacterView, LibraryAsset | null>
}

type AssetCard = { kind: 'asset'; asset: LibraryAsset }

type LibraryCard = CharacterCard | AssetCard

function parseLibraryRole(
  role: string,
): { entityType: 'character' | 'scene' | 'prop' | 'unknown'; entityId: number | null; view?: CharacterView } {
  const text = String(role || '').trim()
  const [prefix, rawId] = text.split(':')
  const entityId = Number.parseInt(String(rawId || '').trim(), 10)
  if (!Number.isFinite(entityId) || entityId <= 0) return { entityType: 'unknown', entityId: null }

  if (prefix === 'lib_character_portrait') return { entityType: 'character', entityId, view: 'front' }
  if (prefix === 'lib_character_portrait_side') return { entityType: 'character', entityId, view: 'side' }
  if (prefix === 'lib_character_portrait_back') return { entityType: 'character', entityId, view: 'back' }
  if (prefix === 'lib_scene_card') return { entityType: 'scene', entityId }
  if (prefix === 'lib_prop_card') return { entityType: 'prop', entityId }
  return { entityType: 'unknown', entityId: null }
}

function characterViewLabel(view: CharacterView): string {
  if (view === 'front') return '正面'
  if (view === 'side') return '侧面'
  return '背面'
}

function characterViewRole(view: CharacterView, entityId: number): string {
  if (view === 'front') return `lib_character_portrait:${entityId}`
  if (view === 'side') return `lib_character_portrait_side:${entityId}`
  return `lib_character_portrait_back:${entityId}`
}

export default function DreamWeaverLibraryPage() {
  const navigate = useNavigate()
  const params = useParams()

  const projectId = useMemo(() => {
    const raw = String(params.projectId || '').trim()
    const id = Number.parseInt(raw, 10)
    return Number.isFinite(id) && id > 0 ? id : 0
  }, [params.projectId])

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
  const [regenStylePreset, setRegenStylePreset] = useState('cinematic_realistic')
  const [regenImageRatio, setRegenImageRatio] = useState('16:9')
  const [regenSubmitting, setRegenSubmitting] = useState(false)
  const [regenSuggesting, setRegenSuggesting] = useState(false)
  const [regenSuggestError, setRegenSuggestError] = useState<string | null>(null)
  const [regenError, setRegenError] = useState<string | null>(null)
  const [characterViewsOpen, setCharacterViewsOpen] = useState(false)
  const [characterViewsEntityId, setCharacterViewsEntityId] = useState<number | null>(null)
  const regenRoleInfo = useMemo(() => parseLibraryRole(regenRole), [regenRole])
  const regenIsSideOrBack = useMemo(() => {
    return (
      regenRoleInfo.entityType === 'character' &&
      (regenRoleInfo.view === 'side' || regenRoleInfo.view === 'back')
    )
  }, [regenRoleInfo])

  const loadLibrary = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    setLibrary(null)
    setLockedConfig(null)
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
          .filter((asset) => !missingRoleSet.has(String(asset?.role || '').trim()))
          .map(async (asset) => {
          try {
            const fileRes = await apiClient.getDreamweaverLibraryAssetFile(asset.id)
            const url = URL.createObjectURL(fileRes.data)
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
      Object.values(previews).forEach((url) => {
        try {
          URL.revokeObjectURL(url)
        } catch {
          // ignore
        }
      })
    }
  }, [previews])

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

  const openRegenerateDialog = (asset: LibraryAsset) => {
    const role = String(asset?.role || '').trim()
    if (!role) return
    const title = String(asset?.meta?.entity_name || asset?.role || '').trim() || role
    const prompt = String(asset?.meta?.prompt || asset?.meta?.suggested_prompt || '').trim()
    const locked = Boolean(lockedConfig?.locked)
    const stylePreset = locked ? normalizeStylePresetValue(lockedConfig?.style_preset) : normalizeStylePresetValue(asset?.meta?.style_preset)
    const ratio = locked ? normalizeImageRatioValue(lockedConfig?.image_ratio) : normalizeImageRatioValue(asset?.meta?.ratio)
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

  const suggestPrompt = useCallback(
    async (mode: 'template' | 'ai') => {
      const role = String(regenRole || '').trim()
      if (!projectId || !role) return
      setRegenSuggesting(true)
      setRegenSuggestError(null)
      try {
        const res = await apiClient.suggestDreamweaverLibraryPrompt(projectId, {
          role,
          prompt: regenPrompt,
          style_preset: regenStylePreset,
          image_ratio: regenImageRatio,
          ...(regenIsSideOrBack ? { prefer_view_chain_seed: true } : {}),
          mode,
        })
        const nextPrompt = String(res.data?.prompt || '').trim()
        if (nextPrompt) setRegenPrompt(nextPrompt)
      } catch (e: any) {
        setRegenSuggestError(await extractApiErrorMessage(e, '生成提示词失败'))
      } finally {
        setRegenSuggesting(false)
      }
    },
    [projectId, regenImageRatio, regenIsSideOrBack, regenPrompt, regenRole, regenStylePreset],
  )

  useEffect(() => {
    if (!regenOpen) return
    if (!projectId) return
    if (!String(regenRole || '').trim()) return
    void suggestPrompt('template')
  }, [regenOpen, regenStylePreset, regenImageRatio])

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
      const title = String(item?.name || '').trim() || `角色:${entityId}`
      const descriptor = String(item?.descriptor || '').trim()
      const views: Record<CharacterView, LibraryAsset | null> = {
        front: assetsByRole.get(characterViewRole('front', entityId)) || null,
        side: assetsByRole.get(characterViewRole('side', entityId)) || null,
        back: assetsByRole.get(characterViewRole('back', entityId)) || null,
      }
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
      out.push({ kind: 'asset', asset })
      usedRoles.add(role)
    }
    return out
  }, [assets, assetsByRole, library?.spec])

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

        {!loading && !library && !error && (
          <Box sx={{ py: 8, display: 'flex', justifyContent: 'center' }}>
            <CircularProgress />
          </Box>
        )}

        {cards.length ? (
          <ImageList variant="masonry" cols={4} gap={10} sx={{ m: 0 }}>
            {cards.map((card) => {
              if (card.kind === 'character') {
                const coverAsset = card.views.front || card.views.side || card.views.back
                const coverPreview = coverAsset ? previews[coverAsset.id] : ''
                const coverAspectRatio = coverAsset
                  ? previewAspectRatios[coverAsset.id] || assetToCssAspectRatio(coverAsset, '16 / 9')
                  : '16 / 9'
                const viewAssets = (['front', 'side', 'back'] as const)
                  .map((v) => card.views[v])
                  .filter((a): a is LibraryAsset => Boolean(a))
                const totalViews = viewAssets.length
                const missingViews = viewAssets.filter((a) => missingRoleSet.has(String(a.role || '').trim())).length
                const approvedViews = viewAssets.filter((a) => Boolean(a?.meta?.approved)).length
                const generatedViews = Math.max(0, totalViews - missingViews)
                return (
                  <ImageListItem
                    key={`character:${card.entityId}`}
                    sx={{
                      border: '1px solid rgba(255,255,255,0.14)',
                      borderRadius: 2,
                      overflow: 'hidden',
                      bgcolor: 'rgba(255,255,255,0.06)',
                      breakInside: 'avoid',
                      cursor: 'pointer',
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
                            setPreviewAspectRatios((prev) =>
                              prev[coverAsset.id] === cssAspectRatio ? prev : { ...prev, [coverAsset.id]: cssAspectRatio },
                            )
                          }}
                          sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                        />
                      )}
                      {!coverPreview && (
                        <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'rgba(255,255,255,0.65)', fontSize: 13 }}>
                          {totalViews === 0 ? '未启用' : missingViews >= totalViews ? '未生成（缺失）' : '暂无预览'}
                        </Box>
                      )}
                    </Box>
                    <Box sx={{ p: 1 }}>
                      <Typography variant="caption" sx={{ fontWeight: 700, color: 'rgba(255,255,255,0.92)' }} display="block">
                        角色：{card.title}
                      </Typography>
                      <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap">
                        <Chip size="small" label={`多视角：${generatedViews}/${totalViews || 0}`} variant="outlined" />
                        <Chip size="small" label={`已通过：${approvedViews}/${totalViews || 0}`} color={approvedViews ? 'success' : 'default'} variant="outlined" />
                        {missingViews > 0 && <Chip size="small" label={`缺失：${missingViews}`} color="warning" variant="outlined" />}
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
                        点击查看正/侧/背面并生成/替换
                      </Typography>
                    </Box>
                  </ImageListItem>
                )
              }

              const asset = card.asset
              const title = assetTitle(asset)
              const preview = previews[asset.id]
              const aspectRatio = previewAspectRatios[asset.id] || assetToCssAspectRatio(asset, '16 / 9')
              const approved = Boolean(asset?.meta?.approved)
              const missing = missingRoleSet.has(String(asset.role || '').trim())
              const parsed = parseLibraryRole(asset.role)
              const chineseRole =
                parsed.entityType === 'scene'
                  ? '场景卡'
                  : parsed.entityType === 'prop'
                    ? '道具卡'
                    : parsed.entityType === 'character' && parsed.view
                      ? `角色立绘（${characterViewLabel(parsed.view)}）`
                      : ''
              const descriptor = String(asset?.meta?.descriptor || '').trim()
              const promptPreview = String(asset?.meta?.prompt || asset?.meta?.suggested_prompt || '').trim()
              return (
                <ImageListItem
                  key={asset.id}
                  sx={{
                    border: '1px solid rgba(255,255,255,0.14)',
                    borderRadius: 2,
                    overflow: 'hidden',
                    bgcolor: 'rgba(255,255,255,0.06)',
                    breakInside: 'avoid',
                  }}
                >
                  <Box sx={{ width: '100%', aspectRatio, bgcolor: 'rgba(0,0,0,0.25)', position: 'relative' }}>
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
                        {!asset ? '未启用' : missing ? '未生成（缺失）' : '暂无预览'}
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
                      {chineseRole && <Chip size="small" label={chineseRole} variant="outlined" />}
                      <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.65)', fontFamily: 'monospace' }}>
                        {asset.role}
                      </Typography>
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
                        disabled={loading}
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
                        {missing ? '生成' : '重生成'}
                      </Button>
                    </Stack>
                  </Box>
                </ImageListItem>
              )
            })}
          </ImageList>
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
            建议：先生成正面，再生成侧面/背面；侧面/背面将强制基于前序视角参考图做图像编辑以保持一致性。
          </Typography>
          <Divider sx={{ my: 2 }} />
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' },
              gap: 1.5,
            }}
          >
            {(['front', 'side', 'back'] as const).map((view) => {
              const asset = characterViewsCard?.views?.[view] || null
              const title = asset ? assetTitle(asset) : ''
              const preview = asset ? previews[asset.id] : ''
              const aspectRatio = asset ? previewAspectRatios[asset.id] || assetToCssAspectRatio(asset, '16 / 9') : '16 / 9'
              const approved = Boolean(asset?.meta?.approved)
              const missing = asset ? missingRoleSet.has(String(asset.role || '').trim()) : true
              return (
                <Box
                  key={view}
                  sx={{
                    border: '1px solid rgba(0,0,0,0.12)',
                    borderRadius: 2,
                    overflow: 'hidden',
                    bgcolor: 'rgba(0,0,0,0.02)',
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
                        {missing ? '未生成（缺失）' : '暂无预览'}
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
                    </Stack>
                    <Stack direction="row" spacing={0.75} alignItems="center" mt={1} sx={{ flexWrap: 'nowrap' }}>
                      <Button
                        size="small"
                        variant="text"
                        onClick={() => asset && void approveLibraryRole(asset.role, !approved)}
                        disabled={loading || !asset}
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
                        onClick={() => asset && openRegenerateDialog(asset)}
                        disabled={loading || !asset}
                        sx={{
                          minWidth: 'auto',
                          px: 1,
                          '& .MuiButton-startIcon': { mr: 0.5 },
                        }}
                      >
                        {missing ? '生成' : '重生成'}
                      </Button>
                    </Stack>
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

      <Dialog
        open={regenOpen}
        onClose={() => {
          if (regenSubmitting) return
          setRegenOpen(false)
        }}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>重生成素材：{regenTitle || regenRole}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            限制：将覆盖重生成并把该素材标记为“待审核”；上传替换仅支持 PNG。
          </Typography>
          {regenIsSideOrBack && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              说明：当前为侧面/背面素材。“AI 生成提示词”会按侧/背面首次生成路径重建，不沿用当前图提示词。
            </Typography>
          )}
          {lockedConfig?.locked && (
            <Alert severity="info" sx={{ mb: 1 }}>
              当前项目的风格/比例/分辨率已锁定，素材库会强制使用锁定配置。
            </Alert>
          )}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1 }}>
            <FormControl fullWidth size="small" disabled={regenSubmitting || regenSuggesting || Boolean(lockedConfig?.locked)}>
              <InputLabel id="library-style-preset-label">风格预设</InputLabel>
              <Select
                labelId="library-style-preset-label"
                value={regenStylePreset}
                label="风格预设"
                onChange={(e) => setRegenStylePreset(String(e.target.value))}
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
                onChange={(e) => setRegenImageRatio(String(e.target.value))}
              >
                <MenuItem value="16:9">横屏 16:9</MenuItem>
                <MenuItem value="9:16">竖屏 9:16</MenuItem>
              </Select>
            </FormControl>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap">
            <Button
              size="small"
              variant="outlined"
              startIcon={<AutoFixHighIcon fontSize="small" />}
              onClick={() => void suggestPrompt('ai')}
              disabled={regenSubmitting || regenSuggesting || !regenRole}
            >
              {regenSuggesting ? '处理中…' : 'AI 生成提示词'}
            </Button>
            <Button
              size="small"
              variant={regenPreferImageEdit ? 'contained' : 'outlined'}
              aria-pressed={regenPreferImageEdit}
              onClick={() => {
                setRegenPreferImageEdit((prev) => {
                  const next = !prev
                  if (next) setRegenPrompt('')
                  return next
                })
              }}
              disabled={regenSubmitting || regenSuggesting}
            >
              编辑图像
            </Button>
          </Stack>
          {regenSuggestError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {regenSuggestError}
            </Alert>
          )}
          <TextField
            label="提示词（可选）"
            fullWidth
            multiline
            minRows={8}
            placeholder={regenPreferImageEdit ? '可以输入要求对原图进行编辑~' : undefined}
            value={regenPrompt}
            onChange={(e) => setRegenPrompt(e.target.value)}
            disabled={regenSubmitting || regenSuggesting}
          />
          {regenError && (
            <Alert severity="error" sx={{ mt: 1 }}>
              {regenError}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRegenOpen(false)} disabled={regenSubmitting}>
            取消
          </Button>
          <Button variant="contained" onClick={submitRegenerateDialog} disabled={regenSubmitting || !regenRole}>
            {regenSubmitting ? '重生成中…' : '确认重生成'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
