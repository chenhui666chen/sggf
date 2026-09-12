import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

import type { UserAssetRecord } from '@/services/api'

import { buildUserAssetPreviewPresentation } from './userAssetPreviewPresentation'

type UserAssetPreviewMediaProps = {
  asset: Pick<UserAssetRecord, 'asset_kind' | 'title'>
  previewUrl?: string | null
  isProtectedAssetPending?: boolean
}

export default function UserAssetPreviewMedia(props: UserAssetPreviewMediaProps) {
  const { asset, previewUrl, isProtectedAssetPending = false } = props
  const { t } = useTranslation()
  const presentation = buildUserAssetPreviewPresentation(asset, {
    previewUrl,
    isProtectedAssetPending,
  }, t)

  if (presentation.kind === 'placeholder') {
    return (
      <Box
        sx={{
          height: 180,
          borderRadius: 2.5,
          bgcolor: 'grey.100',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Typography variant="body2" color="text.secondary">
          {presentation.message}
        </Typography>
      </Box>
    )
  }

  if (presentation.kind === 'video') {
    return (
      <Box
        component="video"
        src={presentation.src}
        controls
        sx={{ width: '100%', height: 180, objectFit: 'cover', borderRadius: 2.5, bgcolor: 'black' }}
      />
    )
  }

  if (presentation.kind === 'audio') {
    return (
      <Box
        sx={{
          height: 180,
          borderRadius: 2.5,
          bgcolor: 'grey.100',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          p: 2,
        }}
      >
        <Box component="audio" src={presentation.src} controls sx={{ width: '100%' }} />
      </Box>
    )
  }

  return (
    <Box
      component="img"
      src={presentation.src}
      alt={presentation.alt}
      sx={{ width: '100%', height: 180, objectFit: 'cover', borderRadius: 2.5, bgcolor: 'black' }}
    />
  )
}
