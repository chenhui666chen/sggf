import type { SyntheticEvent } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import LinkIcon from '@mui/icons-material/Link'
import LinkOffIcon from '@mui/icons-material/LinkOff'
import SyncIcon from '@mui/icons-material/Sync'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import { CHARACTER_VIEW_ORDER, characterViewLabel, characterViewRole } from '@/utils/dreamweaverLibraryRole'
import { resolveLibraryAssetImageState } from '@/utils/dreamweaverLibraryAssetState'
import type { CharacterCard, LibraryAsset, CollectState } from './libraryPageUtils'
import { assetTitle, assetToCssAspectRatio, getKlingProviderRef } from './libraryPageUtils'

export interface CharacterViewDialogProps {
  open: boolean
  card: CharacterCard | null
  loading: boolean
  regenSubmitting: boolean
  previews: Record<number, string>
  previewAspectRatios: Record<number, string>
  setPreviewAspectRatios: React.Dispatch<React.SetStateAction<Record<number, string>>>
  missingRoleSet: Set<string>
  collectStates: Record<number, CollectState>
  requestedLibraryAssetId: number | null
  onClose: () => void
  onApprove: (role: string, approved: boolean) => void
  onUpload: (assetId: number, file: File) => void
  onRegenerate: (asset: LibraryAsset) => void
  onRegenerateForRole: (role: string, title: string) => void
  onCollect: (asset: LibraryAsset) => void
  providerSyncSubmitting: boolean
  providerSyncAssetId: number | null
  onSyncProviderRef: (assetId: number) => Promise<void>
  onOpenProviderRefDialog: (asset: LibraryAsset) => void
}

export function CharacterViewDialog(props: CharacterViewDialogProps) {
  const {
    open,
    card,
    loading,
    regenSubmitting,
    previews,
    previewAspectRatios,
    setPreviewAspectRatios,
    missingRoleSet,
    collectStates,
    requestedLibraryAssetId,
    onClose,
    onApprove,
    onUpload,
    onRegenerate,
    onRegenerateForRole,
    onCollect,
    providerSyncSubmitting,
    providerSyncAssetId,
    onSyncProviderRef,
    onOpenProviderRefDialog,
  } = props

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>角色多视角：{card?.title || '-'}</DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
          {card?.descriptor || '暂无角色描述'}
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
            const role = card ? characterViewRole(view, card.entityId) : ''
            const asset = card?.views?.[view] || null
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
                      onClick={() => asset && void onApprove(asset.role, !approved)}
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
                          void onUpload(asset.id, f)
                        }}
                      />
                    </Button>
                    <Button
                      size="small"
                      variant="contained"
                      startIcon={<AutoFixHighIcon fontSize="small" />}
                      onClick={() => {
                        if (asset) {
                          onRegenerate(asset)
                          return
                        }
                        if (!role) return
                        const roleTitle = `${card?.title || '角色'}-${characterViewLabel(view)}`
                        onRegenerateForRole(role, roleTitle)
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
                      onClick={() => void onCollect(asset)}
                      disabled={loading || collectState.loading || !approved || !hasRenderableImage || state.safetyBlocked}
                      sx={{ mt: 1, width: '100%' }}
                    >
                      {collectState.loading ? '收录中...' : '收录到用户资产'}
                    </Button>
                  ) : null}
                  {asset && hasRenderableImage ? (
                    <Stack direction="row" spacing={0.75} alignItems="center" mt={1} sx={{ flexWrap: 'wrap' }}>
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
                            <Tooltip title="同步 Kling 主体引用到关联视角" arrow>
                              <span>
                                <Button
                                  size="small"
                                  variant="text"
                                  startIcon={<SyncIcon sx={{ fontSize: 14 }} />}
                                  onClick={() => void onSyncProviderRef(asset.id)}
                                  disabled={providerSyncSubmitting && providerSyncAssetId === asset.id}
                                  sx={{ minWidth: 'auto', px: 0.5, fontSize: 11 }}
                                >
                                  {providerSyncSubmitting && providerSyncAssetId === asset.id ? '同步中...' : '同步'}
                                </Button>
                              </span>
                            </Tooltip>
                            <Button
                              size="small"
                              variant="text"
                              startIcon={<LinkOffIcon sx={{ fontSize: 14 }} />}
                              onClick={() => onOpenProviderRefDialog(asset)}
                              sx={{ minWidth: 'auto', px: 0.5, fontSize: 11 }}
                            >
                              解绑
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
                            绑定 Kling
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
                </Box>
              </Box>
            )
          })}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading || regenSubmitting}>
          关闭
        </Button>
      </DialogActions>
    </Dialog>
  )
}
