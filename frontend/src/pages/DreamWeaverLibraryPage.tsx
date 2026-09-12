import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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
  CharacterCard,
} from './dreamweaver-library/libraryPageUtils'
import {
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
  const { t } = useTranslation()
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
        setError(await extractApiErrorMessage(e, t('dreamweaverRun.libraryBatchApproveFailed')))
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
                {t('dreamweaverRun.libraryBackToProjects')}
              </Button>
              <Stack direction="row" spacing={1} alignItems="center">
                <MovieIcon sx={{ fontSize: 26, color: 'white' }} />
                <Typography variant="h6" sx={{ color: 'white', fontWeight: 700 }}>
                  {t('dreamweaverRun.libraryPageTitle')}
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
                {t('dreamweaverRun.libraryRefresh')}
              </Button>
              <Button
                variant="contained"
                color="success"
                onClick={() => projectId && navigate(`/drama/${projectId}`)}
                disabled={!projectId}
              >
                {t('dreamweaverRun.libraryGoToGeneration')}
              </Button>
            </Stack>
          </Box>
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ py: 3 }}>
        {!projectId && <Alert severity="error">{t('dreamweaverRun.libraryInvalidProjectId')}</Alert>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {loading && (
          <Box sx={{ mb: 2 }}>
            <LinearProgress />
          </Box>
        )}

        {/* 合规修订：第三方生成/素材同步服务方提示（素材外观/提示词由所选服务商处理） */}
        <Typography
          variant="caption"
          sx={{ display: 'block', mb: 1.5, color: 'rgba(255,255,255,0.62)', lineHeight: 1.7 }}
        >
          {t('dreamweaverRun.libraryPrivacyNotice')}
        </Typography>

        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
          <Chip label={t('dreamweaverRun.libraryCardsChip', { count: cards.length })} sx={{ color: 'rgba(255,255,255,0.9)', backgroundColor: 'rgba(255,255,255,0.12)' }} />
          <Chip label={t('dreamweaverRun.libraryApprovedChip', { count: approvedCount })} color="success" variant="outlined" />
          <Chip label={t('dreamweaverRun.libraryMissingChip', { count: missingCount })} color={missingCount ? 'warning' : 'default'} variant="outlined" />
          <Chip label={t('dreamweaverRun.libraryPendingChip', { count: unapprovedCount })} color={unapprovedCount ? 'warning' : 'default'} variant="outlined" />
          {missingCount > 0 && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<AutoFixHighIcon fontSize="small" />}
              onClick={() => void openBatchRegenerateConfirm()}
              disabled={loading || batchRegenSubmitting}
              sx={{ color: 'rgba(255,255,255,0.9)', borderColor: 'rgba(255,255,255,0.4)', '&:hover': { borderColor: 'rgba(255,255,255,0.8)', backgroundColor: 'rgba(255,255,255,0.08)' } }}
            >
              {t('dreamweaverRun.libraryBatchRegenMissing')}
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
                label={t('dreamweaverRun.librarySelectedCount', { count: selectedRolesCount })}
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
                {t('dreamweaverRun.libraryBatchApprove')}
              </Button>
              <Button
                size="small"
                variant="outlined"
                color="warning"
                disabled={batchApproving || loading}
                onClick={() => void batchApproveLibraryRoles(false)}
              >
                {t('dreamweaverRun.libraryBatchRevoke')}
              </Button>
              <Button size="small" variant="text" onClick={clearSelection}>
                {t('dreamweaverRun.libraryClearSelection')}
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
              {t('dreamweaverRun.libraryEmptyState')}
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
        imageBaseLabel={t('dreamweaverRun.regenImageBaseLabel')}
        readyReferenceLabel=""
        readyReferenceCount={0}
        missingReferenceLabel=""
        imageEditAutoCleared={false}
        promptInputLabel={t('dreamweaverRun.regenPromptInputLabel')}
        promptValue={regenPrompt}
        promptPlaceholder={regenPreferImageEdit ? t('dreamweaverRun.regenImageEditPlaceholder') : undefined}
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
        derivedViewHintText={t('dreamweaverRun.regenDerivedViewHint')}
        lockedInfoText={lockedConfig?.locked ? t('dreamweaverRun.regenLockedInfo') : undefined}
        extraSettings={
          <>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              {t('dreamweaverRun.regenLimitNote')}
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1 }}>
              <FormControl fullWidth size="small" disabled={regenSubmitting || regenSuggesting || Boolean(lockedConfig?.locked)}>
                <InputLabel id="library-style-preset-label">{t('dreamweaverRun.regenStylePresetLabel')}</InputLabel>
                <Select
                  labelId="library-style-preset-label"
                  value={regenStylePreset}
                  label={t('dreamweaverRun.regenStylePresetLabel')}
                  onChange={(e) => setRegenStylePreset(normalizeStylePresetValue(e.target.value))}
                >
                  <MenuItem value="cinematic_realistic">{t('dreamweaverRun.stylePresetCinematicRealistic')}</MenuItem>
                  <MenuItem value="anime">{t('dreamweaverRun.stylePresetAnime')}</MenuItem>
                  <MenuItem value="ink_wash">{t('dreamweaverRun.stylePresetInkWash')}</MenuItem>
                  <MenuItem value="cyberpunk">{t('dreamweaverRun.stylePresetCyberpunk')}</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" disabled={regenSubmitting || regenSuggesting || Boolean(lockedConfig?.locked)}>
                <InputLabel id="library-image-ratio-label">{t('dreamweaverRun.regenImageRatioLabel')}</InputLabel>
                <Select
                  labelId="library-image-ratio-label"
                  value={regenImageRatio}
                  label={t('dreamweaverRun.regenImageRatioLabel')}
                  onChange={(e) => setRegenImageRatio(normalizeImageRatioValue(e.target.value))}
                >
                  <MenuItem value="16:9">{t('dreamweaverRun.regenRatioLandscape')}</MenuItem>
                  <MenuItem value="9:16">{t('dreamweaverRun.regenRatioPortrait')}</MenuItem>
                </Select>
              </FormControl>
            </Stack>
          </>
        }
      />

      <Dialog open={batchRegenConfirmOpen} onClose={() => { if (!batchRegenSubmitting) cancelBatchRegenerate() }} maxWidth="sm" fullWidth>
        <DialogTitle>{t('dreamweaverRun.libraryBatchRegenMissing')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('dreamweaverRun.libraryBatchRegenConfirmNote', { count: batchRegenRoles.length })}
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
                {t('dreamweaverRun.libraryBatchRegenProgress', { done: batchRegenProgress.done, total: batchRegenProgress.total })}
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
            {t('common.cancel')}
          </Button>
          <Button
            variant="contained"
            color="warning"
            onClick={() => void executeBatchRegenerate()}
            disabled={batchRegenSubmitting || !batchRegenRoles.length}
          >
            {batchRegenSubmitting ? t('dreamweaverRun.libraryBatchRegenSubmitting') : t('dreamweaverRun.libraryBatchRegenConfirmAction', { count: batchRegenRoles.length })}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
