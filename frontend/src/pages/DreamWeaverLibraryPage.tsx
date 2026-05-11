import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
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
import { apiClient } from '@/services/api'
import { useDreamweaverProviderRef } from '@/hooks/useDreamweaverProviderRef'
import { useDreamweaverBatchRegen } from '@/hooks/useDreamweaverBatchRegen'
import LibraryRegenerateDialog from '@/components/dreamweaver/LibraryRegenerateDialog'
import { parseLibraryRole } from '@/utils/dreamweaverLibraryRole'
import {
  buildDreamweaverLibrarySourceActivationPlan,
  buildDreamweaverLibrarySourceScrollPlan,
  readUserAssetSourceLibraryAssetId,
} from '@/utils/userAssetSourceNavigation'
import type {
  LibraryAsset,
  LibraryPayload,
  CharacterCard,
  LibraryCard,
  LibraryCardGroupKey,
  StylePresetValue,
  ImageRatioValue,
} from './dreamweaver-library/libraryPageUtils'
import {
  LIBRARY_CARD_GROUP_ORDER,
  normalizeStylePresetValue,
  normalizeImageRatioValue,
  buildLibraryCards,
  buildCardGroups,
  getKlingProviderRef,
} from './dreamweaver-library/libraryPageUtils'
import { useLibraryData } from './dreamweaver-library/useLibraryData'
import { useLibraryRegenDialog } from './dreamweaver-library/useLibraryRegenDialog'
import { CharacterViewDialog } from './dreamweaver-library/CharacterViewDialog'
import { ProviderRefDialog } from './dreamweaver-library/ProviderRefDialog'
import { LibraryCardGrid } from './dreamweaver-library/LibraryCardGrid'

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

  const {
    library,
    loading,
    error,
    setError,
    lockedConfig,
    previews,
    previewAspectRatios,
    setPreviewAspectRatios,
    assets,
    assetsByRole,
    characterNameById,
    missingRoleSet,
    approvedCount,
    missingCount,
    unapprovedCount,
    collectStates,
    loadLibrary,
    loadLibraryRef,
    approveLibraryRole,
    uploadLibraryAsset,
    collectLibraryAsset,
  } = useLibraryData({ projectId })

  const {
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
    regenIsDerivedCharacterView,
    regenHasCurrentImage,
    openRegenerateDialog,
    openRegenerateDialogForRole,
    setRegenOpen,
    setRegenPrompt,
    setRegenPreferImageEdit,
    setRegenStylePreset,
    setRegenImageRatio,
    submitRegenerateDialog,
    requestSmartRegeneratePrompt,
  } = useLibraryRegenDialog({
    projectId,
    loading,
    lockedConfig,
    assetsByRole,
    characterNameById,
    missingRoleSet,
    loadLibrary,
  })

  const [showAllCards, setShowAllCards] = useState(false)
  const [selectedRoles, setSelectedRoles] = useState<Set<string>>(new Set())
  const [batchApproving, setBatchApproving] = useState(false)
  const [characterViewsOpen, setCharacterViewsOpen] = useState(false)
  const [characterViewsEntityId, setCharacterViewsEntityId] = useState<number | null>(null)
  const handledSourceAssetKeyRef = useRef<string | null>(null)
  const handledSourceAssetScrollKeyRef = useRef<string | null>(null)

  const {
    providerRefDialogOpen,
    providerRefAssetRole,
    providerRefSubjectId,
    providerRefSubmitting,
    providerRefError,
    providerSyncAssetId,
    providerSyncSubmitting,
    openProviderRefDialog,
    closeProviderRefDialog,
    setProviderRefSubjectId,
    submitProviderRef,
    syncProviderRef,
  } = useDreamweaverProviderRef({
    onRefresh: () => loadLibraryRef.current(),
  })

  const {
    batchRegenConfirmOpen,
    batchRegenRoles,
    batchRegenSubmitting,
    batchRegenProgress,
    batchRegenError,
    openBatchRegenerateConfirm,
    executeBatchRegenerate,
    cancelBatchRegenerate,
  } = useDreamweaverBatchRegen({
    projectId,
    onRefresh: () => loadLibraryRef.current(),
    onError: (msg: string) => setError(msg),
  })

  const selectedRolesCount = selectedRoles.size
  const hasSelection = selectedRolesCount > 0

  const toggleRoleSelection = useCallback((role: string) => {
    setSelectedRoles((prev) => {
      const next = new Set(prev)
      if (next.has(role)) next.delete(role)
      else next.add(role)
      return next
    })
  }, [])

  const clearSelection = useCallback(() => setSelectedRoles(new Set()), [])

  const openProviderRefDialogForAsset = useCallback((asset: LibraryAsset) => {
    const { subjectId } = getKlingProviderRef(asset)
    openProviderRefDialog(asset.id, asset.role, subjectId || undefined)
  }, [openProviderRefDialog])

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
        const { extractApiErrorMessage } = await import('@/services/api')
        setError(await extractApiErrorMessage(e, '批量审核失败'))
      } finally {
        setBatchApproving(false)
      }
    },
    [loadLibrary, projectId, selectedRoles, selectedRolesCount, clearSelection, setError],
  )

  const cards = useMemo(
    () => buildLibraryCards(assets, assetsByRole, characterNameById, library?.spec),
    [assets, assetsByRole, characterNameById, library?.spec],
  )

  const cardGroups = useMemo(
    () => buildCardGroups(cards),
    [cards],
  )

  const characterViewsCard = useMemo(() => {
    if (!characterViewsEntityId) return null
    return cards.find((c): c is CharacterCard => c.kind === 'character' && c.entityId === characterViewsEntityId) || null
  }, [cards, characterViewsEntityId])

  const requestedLibraryAsset = useMemo(
    () => (requestedLibraryAssetId ? assets.find((asset) => asset.id === requestedLibraryAssetId) || null : null),
    [assets, requestedLibraryAssetId],
  )
  const requestedCharacterEntityId = useMemo(() => {
    if (!requestedLibraryAsset) return null
    const parsed = parseLibraryRole(String(requestedLibraryAsset.role || '').trim())
    return parsed.entityType === 'character' && parsed.entityId ? parsed.entityId : null
  }, [requestedLibraryAsset])

  const openCharacterViews = useCallback((card: CharacterCard) => {
    setCharacterViewsEntityId(card.entityId)
    setCharacterViewsOpen(true)
  }, [])

  const closeCharacterViews = useCallback(() => {
    if (loading || regenSubmitting) return
    setCharacterViewsOpen(false)
    setCharacterViewsEntityId(null)
  }, [loading, regenSubmitting])

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

  const handleBatchRegenMissing = useCallback((roles: string[]) => {
    for (const role of roles) {
      void apiClient.regenerateDreamweaverLibraryAsset(projectId!, { role })
    }
  }, [projectId])

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
          {missingCount > 0 && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<AutoFixHighIcon fontSize="small" />}
              onClick={() => void openBatchRegenerateConfirm()}
              disabled={loading || batchRegenSubmitting}
              sx={{ color: 'rgba(255,255,255,0.9)', borderColor: 'rgba(255,255,255,0.4)', '&:hover': { borderColor: 'rgba(255,255,255,0.8)', backgroundColor: 'rgba(255,255,255,0.08)' } }}
            >
              批量重生成缺失素材
            </Button>
          )}
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
          <LibraryCardGrid
            cards={cards}
            cardGroups={cardGroups}
            showAllCards={showAllCards}
            onShowAllCards={setShowAllCards}
            cardCols={cardCols}
            loading={loading}
            previews={previews}
            previewAspectRatios={previewAspectRatios}
            setPreviewAspectRatios={setPreviewAspectRatios}
            missingRoleSet={missingRoleSet}
            requestedLibraryAssetId={requestedLibraryAssetId}
            requestedCharacterEntityId={requestedCharacterEntityId}
            selectedRoles={selectedRoles}
            onToggleRoleSelection={toggleRoleSelection}
            collectStates={collectStates}
            characterNameById={characterNameById}
            onApprove={approveLibraryRole}
            onUpload={uploadLibraryAsset}
            onRegenerate={openRegenerateDialog}
            onCollect={collectLibraryAsset}
            onOpenCharacterViews={openCharacterViews}
            providerSyncSubmitting={providerSyncSubmitting}
            providerSyncAssetId={providerSyncAssetId}
            onSyncProviderRef={syncProviderRef}
            onOpenProviderRefDialog={openProviderRefDialogForAsset}
            onBatchRegenMissing={handleBatchRegenMissing}
          />
        ) : (
          !loading && (
            <Typography sx={{ color: 'rgba(255,255,255,0.75)' }}>
              当前项目暂无素材库资产（或尚未生成）。进入生成流程后可在"素材"阶段加载/生成素材库。
            </Typography>
          )
        )}
      </Container>

      <CharacterViewDialog
        open={characterViewsOpen}
        card={characterViewsCard}
        loading={loading}
        regenSubmitting={regenSubmitting}
        previews={previews}
        previewAspectRatios={previewAspectRatios}
        setPreviewAspectRatios={setPreviewAspectRatios}
        missingRoleSet={missingRoleSet}
        collectStates={collectStates}
        requestedLibraryAssetId={requestedLibraryAssetId}
        onClose={closeCharacterViews}
        onApprove={approveLibraryRole}
        onUpload={uploadLibraryAsset}
        onRegenerate={openRegenerateDialog}
        onRegenerateForRole={openRegenerateDialogForRole}
        onCollect={collectLibraryAsset}
        providerSyncSubmitting={providerSyncSubmitting}
        providerSyncAssetId={providerSyncAssetId}
        onSyncProviderRef={syncProviderRef}
        onOpenProviderRefDialog={openProviderRefDialogForAsset}
      />

      <ProviderRefDialog
        open={providerRefDialogOpen}
        assetRole={providerRefAssetRole}
        subjectId={providerRefSubjectId}
        submitting={providerRefSubmitting}
        error={providerRefError}
        onSubjectIdChange={setProviderRefSubjectId}
        onClose={closeProviderRefDialog}
        onSubmit={submitProviderRef}
      />

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
              限制：将覆盖重生成并把该素材标记为"待审核"；上传替换仅支持 PNG。
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

      <Dialog open={batchRegenConfirmOpen} onClose={() => { if (!batchRegenSubmitting) cancelBatchRegenerate() }} maxWidth="sm" fullWidth>
        <DialogTitle>批量重生成缺失素材</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            以下 {batchRegenRoles.length} 个缺失素材角色将被提交重生成：
          </Typography>
          <Box sx={{ maxHeight: 300, overflow: 'auto', mb: 2 }}>
            {batchRegenRoles.map((role: string) => (
              <Chip key={role} size="small" label={role} variant="outlined" sx={{ m: 0.25 }} />
            ))}
          </Box>
          {batchRegenProgress && (
            <Box sx={{ mb: 1 }}>
              <LinearProgress variant="determinate" value={(batchRegenProgress.done / batchRegenProgress.total) * 100} />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                进度：{batchRegenProgress.done} / {batchRegenProgress.total}
              </Typography>
            </Box>
          )}
          {batchRegenError && (
            <Alert severity="error" sx={{ mt: 1, borderRadius: 2 }}>
              {batchRegenError}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={cancelBatchRegenerate} disabled={batchRegenSubmitting}>
            取消
          </Button>
          <Button
            variant="contained"
            color="warning"
            onClick={() => void executeBatchRegenerate()}
            disabled={batchRegenSubmitting || !batchRegenRoles.length}
          >
            {batchRegenSubmitting ? '重生成中...' : `确认重生成 (${batchRegenRoles.length})`}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
