import {
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Grid,
  Stack,
  Typography,
} from '@mui/material'

import {
  getUserAssetSourceInfo,
  type UserAssetProjectTitleMap,
} from '@/contracts/userAssetSourceReaders'
import {
  isUserAssetPreviewPending,
  resolveUserAssetPreviewUrl,
} from '@/contracts/userAssetPreviewResolvers'
import { useTranslation } from 'react-i18next'

import type { UserAssetRecord } from '@/services/api'

import UserAssetPreviewMedia from './UserAssetPreviewMedia'
import { buildUserAssetCardPresentation } from './userAssetCardPresentation'

type UserAssetCardProps = {
  asset: UserAssetRecord
  projectTitleMap?: UserAssetProjectTitleMap
  localObjectUrl?: string | null
  protectedObjectUrl?: string | null
  createdAtLabel: string
  isSelected: boolean
  batchDisabled?: boolean
  isSubmitting?: boolean
  onToggleSelection: () => void
  onNavigateToSource: (path: string) => void
  onEdit: () => void
  onRestoreLocalCopy: () => void
  onClearLocalCopy: () => void
  onToggleFavorite: () => void
  onToggleArchived: () => void
}

export default function UserAssetCard(props: UserAssetCardProps) {
  const {
    asset,
    projectTitleMap,
    localObjectUrl,
    protectedObjectUrl,
    createdAtLabel,
    isSelected,
    batchDisabled = false,
    isSubmitting = false,
    onToggleSelection,
    onNavigateToSource,
    onEdit,
    onRestoreLocalCopy,
    onClearLocalCopy,
    onToggleFavorite,
    onToggleArchived,
  } = props

  const { t } = useTranslation()
  const sourceInfo = getUserAssetSourceInfo(asset, projectTitleMap, t)
  const previewUrl = resolveUserAssetPreviewUrl(asset, {
    localObjectUrl,
    protectedObjectUrl,
  })
  const isProtectedAssetPending = isUserAssetPreviewPending(asset, {
    localObjectUrl,
    protectedObjectUrl,
  })
  const presentation = buildUserAssetCardPresentation(asset, sourceInfo, {
    createdAtLabel,
    hasLocalObjectUrl: Boolean(localObjectUrl),
  }, t)

  return (
    <Grid item xs={12} md={6} lg={4}>
      <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
        <CardContent>
          <UserAssetPreviewMedia
            asset={asset}
            previewUrl={previewUrl}
            isProtectedAssetPending={isProtectedAssetPending}
          />
          <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
            {presentation.headerChips.map((chip) => (
              <Chip
                key={chip.key}
                size="small"
                color={chip.color}
                variant={chip.variant}
                label={chip.label}
              />
            ))}
          </Stack>

          <Stack direction="row" justifyContent="flex-end" alignItems="center" sx={{ mt: 0.25 }}>
            <Typography variant="caption" color="text.secondary">
              {presentation.selectionLabel}
            </Typography>
            <Checkbox
              size="small"
              checked={isSelected}
              onChange={onToggleSelection}
              disabled={batchDisabled}
            />
          </Stack>

          <Typography variant="h6" sx={{ mt: 1.5, fontWeight: 700 }}>
            {asset.title}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
            {presentation.description}
          </Typography>
          <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1 }}>
            {presentation.sourceSummary}
          </Typography>

          <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
            {presentation.detailChips.map((chip) => (
              <Chip
                key={chip.key}
                size="small"
                color={chip.color}
                variant={chip.variant}
                label={chip.label}
              />
            ))}
          </Stack>

          <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1.5 }}>
            {presentation.createdAtLabel}
          </Typography>

          <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', rowGap: 1 }}>
            {presentation.sourceAction?.path ? (
              <Button
                size="small"
                variant="outlined"
                onClick={() => onNavigateToSource(presentation.sourceAction?.path || '/user-center')}
              >
                {presentation.sourceAction.label}
              </Button>
            ) : null}
            <Button size="small" variant="outlined" onClick={onEdit}>
              {presentation.editAction.label}
            </Button>
            {presentation.restoreLocalAction ? (
              <Button size="small" variant="outlined" disabled={isSubmitting} onClick={onRestoreLocalCopy}>
                {presentation.restoreLocalAction.label}
              </Button>
            ) : null}
            {presentation.clearLocalAction ? (
              <Button size="small" variant="outlined" disabled={isSubmitting} onClick={onClearLocalCopy}>
                {presentation.clearLocalAction.label}
              </Button>
            ) : null}
            <Button size="small" variant="outlined" disabled={isSubmitting} onClick={onToggleFavorite}>
              {presentation.favoriteAction.label}
            </Button>
            <Button size="small" variant="outlined" disabled={isSubmitting} onClick={onToggleArchived}>
              {presentation.archiveAction.label}
            </Button>
          </Stack>
        </CardContent>
      </Card>
    </Grid>
  )
}
