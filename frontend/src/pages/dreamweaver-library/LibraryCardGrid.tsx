import type { SyntheticEvent } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  ImageList,
  ImageListItem,
  Stack,
  Typography,
} from '@mui/material'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import LinkIcon from '@mui/icons-material/Link'
import LinkOffIcon from '@mui/icons-material/LinkOff'
import SyncIcon from '@mui/icons-material/Sync'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import { CHARACTER_VIEW_ORDER, characterViewLabel, characterViewRole, parseLibraryRole } from '@/utils/dreamweaverLibraryRole'
import { resolveLibraryAssetImageState } from '@/utils/dreamweaverLibraryAssetState'
import type { LibraryCard, LibraryCardGroupKey, LibraryAsset, CollectState, CharacterCard } from './libraryPageUtils'
import { LIBRARY_CARD_GROUP_ORDER, assetToCssAspectRatio, getKlingProviderRef, getLibraryAssetDisplayTitle } from './libraryPageUtils'
import { useTranslation } from 'react-i18next'

export interface LibraryCardGridProps {
  cards: LibraryCard[]
  cardGroups: Record<LibraryCardGroupKey, LibraryCard[]>
  showAllCards: boolean
  onShowAllCards: (v: boolean) => void
  cardCols: number
  loading: boolean
  previews: Record<number, string>
  previewAspectRatios: Record<number, string>
  setPreviewAspectRatios: React.Dispatch<React.SetStateAction<Record<number, string>>>
  missingRoleSet: Set<string>
  requestedLibraryAssetId: number | null
  requestedCharacterEntityId: number | null
  selectedRoles: Set<string>
  onToggleRoleSelection: (role: string) => void
  collectStates: Record<number, CollectState>
  characterNameById: Map<number, string>
  onApprove: (role: string, approved: boolean) => void
  onUpload: (assetId: number, file: File) => void
  onRegenerate: (asset: LibraryAsset) => void
  onCollect: (asset: LibraryAsset) => void
  onOpenCharacterViews: (card: CharacterCard) => void
  providerSyncSubmitting: boolean
  providerSyncAssetId: number | null
  onSyncProviderRef: (assetId: number) => Promise<void>
  onOpenProviderRefDialog: (asset: LibraryAsset) => void
  onBatchRegenMissing: (roles: string[]) => void
}

const INITIAL_CARD_LIMIT = 20

export function LibraryCardGrid(props: LibraryCardGridProps) {
  const { t } = useTranslation()
  const {
    cards,
    cardGroups,
    showAllCards,
    onShowAllCards,
    cardCols,
    loading,
    previews,
    previewAspectRatios,
    setPreviewAspectRatios,
    missingRoleSet,
    requestedLibraryAssetId,
    requestedCharacterEntityId,
    selectedRoles,
    onToggleRoleSelection,
    collectStates,
    characterNameById,
    onApprove,
    onUpload,
    onRegenerate,
    onCollect,
    onOpenCharacterViews,
    providerSyncSubmitting,
    providerSyncAssetId,
    onSyncProviderRef,
    onOpenProviderRefDialog,
    onBatchRegenMissing,
  } = props

  const renderCharacterCard = (card: CharacterCard) => {
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

    let emptyText = t('dreamweaverRun.libraryNoPreview')
    if (generatedViews <= 0) {
      if (missingViews >= totalViews) emptyText = t('dreamweaverRun.libraryPreviewMissingAll')
      else if (blockedViews > 0) emptyText = t('dreamweaverRun.libraryStatusSafetyBlocked')
      else if (placeholderViews > 0) emptyText = t('dreamweaverRun.libraryPlaceholderImage')
      else emptyText = t('dreamweaverRun.libraryPreviewNotGenerated')
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
        onClick={() => onOpenCharacterViews(card)}
        role="button"
        tabIndex={0}
        aria-label={t('dreamweaverRun.libraryViewAriaLabel', { title: card.title })}
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
            {t('dreamweaverRun.libraryRoleLabel', { title: card.title })}
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap">
            <Chip size="small" label={t('dreamweaverRun.libraryViewCountChip', { generated: generatedViews, total: totalViews })} variant="outlined" />
            <Chip size="small" label={t('dreamweaverRun.libraryApprovedViewChip', { approved: approvedViews, total: totalViews })} color={approvedViews ? 'success' : 'default'} variant="outlined" />
            {missingViews > 0 && <Chip size="small" label={t('dreamweaverRun.libraryMissingViewChip', { count: missingViews })} color="warning" variant="outlined" />}
            {placeholderViews > 0 && <Chip size="small" label={t('dreamweaverRun.libraryPlaceholderViewChip', { count: placeholderViews })} variant="outlined" />}
            {blockedViews > 0 && <Chip size="small" label={t('dreamweaverRun.libraryBlockedViewChip', { count: blockedViews })} color="error" variant="outlined" />}
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
          {missingViews > 0 && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<AutoFixHighIcon sx={{ fontSize: 14 }} />}
              disabled={loading}
              onClick={(e) => {
                e.stopPropagation()
                const missingRoles = viewItems.filter((item) => item.markedMissing && item.role).map((item) => item.role)
                if (!missingRoles.length) return
                onBatchRegenMissing(missingRoles)
              }}
              sx={{ mt: 0.75, fontSize: 11, color: 'rgba(255,255,255,0.85)', borderColor: 'rgba(255,255,255,0.35)', '&:hover': { borderColor: 'rgba(255,255,255,0.7)', backgroundColor: 'rgba(255,255,255,0.08)' } }}
            >
              {t('dreamweaverRun.libraryRegenerateMissingViews', { count: missingViews })}
            </Button>
          )}
          <Typography variant="caption" sx={{ display: 'block', mt: 0.75, color: 'rgba(255,255,255,0.55)' }}>
            {t('dreamweaverRun.libraryCardClickHint')}
          </Typography>
        </Box>
      </ImageListItem>
    )
  }

  const renderAssetCard = (asset: LibraryAsset) => {
    const parsed = parseLibraryRole(asset.role)
    const title = getLibraryAssetDisplayTitle(asset, characterNameById)
    const imageState = resolveLibraryAssetImageState(asset, { missingRoleSet })
    const preview = imageState.hasRenderableImage ? previews[asset.id] : ''
    const aspectRatio = previewAspectRatios[asset.id] || assetToCssAspectRatio(asset, '16 / 9')
    const approved = imageState.hasRenderableImage && Boolean(asset?.meta?.approved)
    const missing = imageState.markedMissing
    const placeholder = imageState.placeholder && !missing && !imageState.safetyBlocked
    const collectState = collectStates[asset.id] || { loading: false, feedback: null }
    const chineseRole =
      parsed.entityType === 'scene'
        ? t('dreamweaverRun.libraryTypeScene')
        : parsed.entityType === 'prop'
          ? t('dreamweaverRun.libraryTypeProp')
          : parsed.entityType === 'character' && parsed.view
            ? t('dreamweaverRun.libraryTypeCharacterView', { view: characterViewLabel(parsed.view) })
            : ''
    const showRawRole = parsed.entityType === 'unknown'
    const descriptor = String(asset?.meta?.descriptor || '').trim()
    const promptPreview = String(asset?.meta?.prompt || asset?.meta?.suggested_prompt || '').trim()
    const statusText = missing
      ? t('dreamweaverRun.libraryPreviewMissingAll')
      : imageState.safetyBlocked
        ? t('dreamweaverRun.libraryStatusSafetyBlocked')
        : placeholder
          ? t('dreamweaverRun.libraryPlaceholderImage')
          : t('dreamweaverRun.libraryNoPreview')

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
            onChange={() => onToggleRoleSelection(asset.role)}
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
            <Chip size="small" label={approved ? t('dreamweaverRun.libraryStatusApproved') : t('dreamweaverRun.libraryStatusPendingReview')} color={approved ? 'success' : 'default'} />
            {missing && <Chip size="small" label={t('dreamweaverRun.libraryStatusMissing')} color="warning" variant="outlined" />}
            {placeholder && <Chip size="small" label={t('dreamweaverRun.libraryStatusPlaceholder')} variant="outlined" />}
            {imageState.safetyBlocked && <Chip size="small" label={t('dreamweaverRun.libraryStatusSafetyBlocked')} color="error" variant="outlined" />}
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
              onClick={() => void onApprove(asset.role, !approved)}
              disabled={loading || !imageState.hasRenderableImage || imageState.safetyBlocked}
            >
              {approved ? t('dreamweaverRun.libraryRevokeApproval') : t('dreamweaverRun.libraryApprove')}
            </Button>
            <Button
              size="small"
              variant="outlined"
              component="label"
              startIcon={<UploadFileIcon fontSize="small" />}
              disabled={loading}
            >
              {t('dreamweaverRun.libraryUploadReplace')}
              <input
                hidden
                type="file"
                accept="image/png"
                onChange={(e) => {
                  const f = e.target.files && e.target.files[0]
                  e.target.value = ''
                  if (!f) return
                  void onUpload(asset.id, f)
                }}
              />
            </Button>
            <Button
              size="small"
              variant="contained"
              startIcon={<AutoFixHighIcon fontSize="small" />}
              onClick={() => onRegenerate(asset)}
              disabled={loading}
            >
              {imageState.hasRenderableImage ? t('dreamweaverRun.libraryRegenerate') : t('dreamweaverRun.libraryGenerate')}
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={() => void onCollect(asset)}
              disabled={loading || collectState.loading || !approved || !imageState.hasRenderableImage || imageState.safetyBlocked}
            >
              {collectState.loading ? t('dreamweaverRun.libraryCollecting') : t('dreamweaverRun.libraryCollectToUserAssets')}
            </Button>
          </Stack>
          {imageState.hasRenderableImage ? (
            <Stack direction="row" spacing={0.75} alignItems="center" mt={0.75} flexWrap="wrap">
              {(() => {
                const klingRef = getKlingProviderRef(asset)
                return klingRef.subjectId ? (
                  <>
                    <Chip
                      size="small"
                      icon={<LinkIcon sx={{ fontSize: 14 }} />}
                      label={`Kling: ${klingRef.subjectId.slice(0, 8)}${klingRef.subjectId.length > 8 ? '...' : ''}`}
                      color="info"
                      variant="outlined"
                    />
                    <Button
                      size="small"
                      variant="text"
                      startIcon={<SyncIcon sx={{ fontSize: 14 }} />}
                      onClick={() => void onSyncProviderRef(asset.id)}
                      disabled={providerSyncSubmitting && providerSyncAssetId === asset.id}
                      sx={{ minWidth: 'auto', px: 0.5, fontSize: 11 }}
                    >
                      {providerSyncSubmitting && providerSyncAssetId === asset.id ? t('dreamweaverRun.librarySyncing') : t('dreamweaverRun.librarySync')}
                    </Button>
                    <Button
                      size="small"
                      variant="text"
                      startIcon={<LinkOffIcon sx={{ fontSize: 14 }} />}
                      onClick={() => onOpenProviderRefDialog(asset)}
                      sx={{ minWidth: 'auto', px: 0.5, fontSize: 11 }}
                    >
                      {t('dreamweaverRun.libraryUnbind')}
                    </Button>
                  </>
                ) : (
                  <Button
                    size="small"
                    variant="text"
                    startIcon={<LinkIcon sx={{ fontSize: 14 }} />}
                    onClick={() => onOpenProviderRefDialog(asset)}
                    sx={{ minWidth: 'auto', px: 0.5, fontSize: 11 }}
                  >
                    {t('dreamweaverRun.libraryBindKling')}
                  </Button>
                )
              })()}
            </Stack>
          ) : null}
          {collectState.feedback ? (
            <Alert severity={collectState.feedback.type} sx={{ mt: 1, borderRadius: 2 }}>
              {collectState.feedback.text}
            </Alert>
          ) : null}
          {!approved && imageState.hasRenderableImage && !imageState.safetyBlocked ? (
            <Typography variant="caption" sx={{ display: 'block', mt: 0.75, color: 'rgba(255,255,255,0.55)' }}>
              {t('dreamweaverRun.libraryApproveFirstHint')}
            </Typography>
          ) : null}
        </Box>
      </ImageListItem>
    )
  }

  const renderLibraryCard = (card: LibraryCard) => {
    if (card.kind === 'character') return renderCharacterCard(card)
    return renderAssetCard(card.asset)
  }

  return (
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
                {t(group.labelKey)}
              </Typography>
              <Chip size="small" label={t('dreamweaverRun.libraryItemCount', { count: items.length })} variant="outlined" />
              {hasMore && !showAllCards && (
                <Chip
                  size="small"
                  label={t('dreamweaverRun.libraryShowMore')}
                  variant="outlined"
                  color="primary"
                  onClick={() => onShowAllCards(true)}
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
                onClick={() => onShowAllCards(true)}
                sx={{ mt: 1, color: 'rgba(255,255,255,0.85)', borderColor: 'rgba(255,255,255,0.3)' }}
              >
                {t('dreamweaverRun.libraryShowAll', { count: items.length })}
              </Button>
            )}
          </Box>
        )
      })}
      {showAllCards && cards.length > INITIAL_CARD_LIMIT && (
        <Button
          size="small"
          variant="outlined"
          onClick={() => onShowAllCards(false)}
          sx={{ color: 'rgba(255,255,255,0.85)', borderColor: 'rgba(255,255,255,0.3)' }}
        >
          {t('dreamweaverRun.libraryCollapse')}
        </Button>
      )}
    </Stack>
  )
}
