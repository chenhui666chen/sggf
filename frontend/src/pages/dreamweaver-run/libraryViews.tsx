import type { ReactNode } from 'react'

import { Box, Button, Chip, ImageListItem, Stack, Typography } from '@mui/material'

type DreamweaverLibraryDisplayCardStateProps = {
  preview?: string | null
  safetyBlocked: boolean
  placeholder: boolean
  placeholderText: string
  placeholderColor: string
  placeholderBackgroundImage: string
  backgroundColor: string
  statusLabel: string
  statusColor: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning'
  hasRenderableImage: boolean
  approved: boolean
  previewError?: string | null
  previewLoading: boolean
  safetyError?: string | null
  roleLabel?: string | null
  canGenerate: boolean
  hasAsset: boolean
}

type DreamweaverLibraryDisplayCardProps = {
  itemKey: string
  title: string
  aspectRatio: string
  state: DreamweaverLibraryDisplayCardStateProps
  libraryLoading: boolean
  onToggleApprove?: () => void
  onLoadPreview?: () => void
  onOpenRegenerate: () => void
}

function DreamweaverLibraryDisplayCardPreviewArea({
  title,
  aspectRatio,
  state,
}: {
  title: string
  aspectRatio: string
  state: DreamweaverLibraryDisplayCardStateProps
}) {
  return (
    <Box
      sx={{
        width: '100%',
        aspectRatio,
        bgcolor: state.backgroundColor,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {state.preview && !state.safetyBlocked ? (
        <Box
          component="img"
          src={state.preview}
          alt={title}
          loading="lazy"
          sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      ) : (
        <Box
          sx={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            color: state.placeholderColor,
            fontSize: 12,
            backgroundImage: state.placeholderBackgroundImage,
          }}
        >
          {state.safetyBlocked && <Box sx={{ fontSize: 24, mb: 0.5 }}>⛔️</Box>}
          <Box>{state.placeholderText}</Box>
          {state.safetyBlocked && (
            <Box sx={{ fontSize: 10, mt: 0.5, px: 1, textAlign: 'center', opacity: 0.8 }}>
              点击重新生成
            </Box>
          )}
        </Box>
      )}
      <Box sx={{ position: 'absolute', top: 8, left: 8 }}>
        <Chip size="small" label={state.statusLabel} color={state.statusColor} />
      </Box>
      {state.placeholder && (
        <Box sx={{ position: 'absolute', top: 8, right: 8 }}>
          <Chip size="small" label="占位" variant="outlined" color="warning" />
        </Box>
      )}
    </Box>
  )
}

function DreamweaverLibraryDisplayCardErrors({
  safetyError,
  previewError,
}: {
  safetyError?: string | null
  previewError?: string | null
}) {
  return (
    <>
      {safetyError && (
        <Typography variant="caption" color="error" display="block" sx={{ mb: 0.5, fontSize: '0.7rem', wordBreak: 'break-all' }}>
          {safetyError.slice(0, 100)}
          {safetyError.length > 100 ? '...' : ''}
        </Typography>
      )}
      {previewError && (
        <Typography variant="caption" color="error" display="block" sx={{ mb: 0.5, fontSize: '0.7rem', wordBreak: 'break-all' }}>
          {previewError.slice(0, 100)}
          {previewError.length > 100 ? '...' : ''}
        </Typography>
      )}
    </>
  )
}

function DreamweaverLibraryDisplayCardActions({
  state,
  libraryLoading,
  onToggleApprove,
  onLoadPreview,
  onOpenRegenerate,
}: {
  state: DreamweaverLibraryDisplayCardStateProps
  libraryLoading: boolean
  onToggleApprove?: () => void
  onLoadPreview?: () => void
  onOpenRegenerate: () => void
}) {
  return (
    <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap">
      {state.hasAsset ? (
        <>
          {!state.safetyBlocked && state.hasRenderableImage && onToggleApprove && (
            <Button size="small" variant="text" onClick={onToggleApprove} disabled={libraryLoading}>
              {state.approved ? '撤销' : '通过'}
            </Button>
          )}
          {!state.safetyBlocked && state.hasRenderableImage && (!state.preview || state.previewError) && onLoadPreview && (
            <Button size="small" variant="text" onClick={onLoadPreview} disabled={libraryLoading || state.previewLoading}>
              {state.previewLoading ? '加载中…' : state.preview ? '重新加载预览' : '加载预览'}
            </Button>
          )}
          <Button
            size="small"
            variant={state.safetyBlocked ? 'contained' : 'text'}
            color={state.safetyBlocked ? 'warning' : 'primary'}
            onClick={onOpenRegenerate}
            disabled={libraryLoading}
          >
            {state.hasRenderableImage ? '重新生成' : '生成素材'}
          </Button>
        </>
      ) : state.canGenerate ? (
        <Button size="small" variant="text" onClick={onOpenRegenerate} disabled={libraryLoading}>
          生成素材
        </Button>
      ) : (
        <Chip size="small" label="等待生成" variant="outlined" />
      )}
    </Stack>
  )
}

export function DreamweaverLibraryDisplayCard({
  itemKey,
  title,
  aspectRatio,
  state,
  libraryLoading,
  onToggleApprove,
  onLoadPreview,
  onOpenRegenerate,
}: DreamweaverLibraryDisplayCardProps) {
  return (
    <ImageListItem key={itemKey} sx={{ border: '1px solid #eee', borderRadius: 2, overflow: 'hidden' }}>
      <DreamweaverLibraryDisplayCardPreviewArea title={title} aspectRatio={aspectRatio} state={state} />
      <Box sx={{ p: 1 }}>
        <Typography variant="caption" sx={{ fontWeight: 600 }} display="block">
          {title}
        </Typography>
        {state.roleLabel && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
            {state.roleLabel}
          </Typography>
        )}
        <DreamweaverLibraryDisplayCardErrors safetyError={state.safetyError} previewError={state.previewError} />
        <DreamweaverLibraryDisplayCardActions
          state={state}
          libraryLoading={libraryLoading}
          onToggleApprove={onToggleApprove}
          onLoadPreview={onLoadPreview}
          onOpenRegenerate={onOpenRegenerate}
        />
      </Box>
    </ImageListItem>
  )
}

type DreamweaverLibraryGroupSummaryProps = {
  total: number
  generated: number
  processing: number
  planned: number
  approved: number
  pendingReview: number
}

type DreamweaverLibrarySummaryChipsProps = {
  totalLabel: string
  summary: DreamweaverLibraryGroupSummaryProps
}

export function DreamweaverLibrarySummaryChips({
  totalLabel,
  summary,
}: DreamweaverLibrarySummaryChipsProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      <Chip size="small" label={`${totalLabel} ${summary.total}`} />
      <Chip size="small" label={`已生成 ${summary.generated}`} color={summary.generated ? 'success' : 'default'} />
      <Chip size="small" label={`生成中 ${summary.processing}`} color={summary.processing ? 'info' : 'default'} />
      <Chip size="small" label={`待生成 ${summary.planned}`} />
      {summary.approved > 0 && <Chip size="small" label={`已通过 ${summary.approved}`} color="success" />}
      {summary.pendingReview > 0 && <Chip size="small" label={`待审核 ${summary.pendingReview}`} color="warning" />}
    </Stack>
  )
}

type DreamweaverCharacterLibraryBucketSectionProps = {
  bucketKey: string
  name: string
  viewCount: number
  generatedCount: number
  content: ReactNode
}

export function DreamweaverCharacterLibraryBucketSection({
  bucketKey,
  name,
  viewCount,
  generatedCount,
  content,
}: DreamweaverCharacterLibraryBucketSectionProps) {
  return (
    <Box key={bucketKey} sx={{ border: '1px solid #eee', borderRadius: 2, p: 1, bgcolor: '#fcfcfc' }}>
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 0.5 }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {name}
        </Typography>
        <Chip size="small" label={`视角 ${viewCount}`} variant="outlined" />
        <Chip size="small" label={`已生成 ${generatedCount}`} color={generatedCount ? 'success' : 'default'} />
      </Stack>
      {content}
    </Box>
  )
}

type DreamweaverLibraryGroupSectionProps = {
  groupKey: string
  label: string
  summaryChips: ReactNode
  content: ReactNode
}

export function DreamweaverLibraryGroupSection({
  groupKey,
  label,
  summaryChips,
  content,
}: DreamweaverLibraryGroupSectionProps) {
  return (
    <Box key={groupKey} sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {label}
        </Typography>
      </Stack>
      {summaryChips}
      {content}
    </Box>
  )
}
