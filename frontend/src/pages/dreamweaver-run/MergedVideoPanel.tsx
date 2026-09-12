import { Alert, Box, Button, Stack } from '@mui/material'

import { useTranslation } from 'react-i18next'

export interface MergedVideoPanelProps {
  currentRunId: string | null
  mergedVideoLoading: boolean
  mergedVideoError: string | null
  mergedVideoPreviewUrl: string | null
  mergedVideoPreviewPortrait: boolean
  mergedVideoCollecting: boolean
  mergedVideoCollectFeedback: { type: 'success' | 'error' | 'info'; text: string } | null
  onLoadPreview: () => void
  onDownload: () => void
  onCollect: () => void
  centeredPreview?: boolean
}

export function MergedVideoPanel({
  currentRunId,
  mergedVideoLoading,
  mergedVideoError,
  mergedVideoPreviewUrl,
  mergedVideoPreviewPortrait,
  mergedVideoCollecting,
  mergedVideoCollectFeedback,
  onLoadPreview,
  onDownload,
  onCollect,
  centeredPreview,
}: MergedVideoPanelProps) {
  const { t } = useTranslation()
  return (
    <>
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
        <Button
          size="small"
          variant="outlined"
          onClick={onLoadPreview}
          disabled={!currentRunId || mergedVideoLoading}
        >
          {mergedVideoLoading ? t('dreamweaverRun.libraryLoadingText') : mergedVideoPreviewUrl ? t('dreamweaverRun.mvReload') : t('dreamweaverRun.mvLoadPreview')}
        </Button>
        <Button
          size="small"
          variant="contained"
          onClick={onDownload}
          disabled={!currentRunId || mergedVideoLoading}
        >
          {t('dreamweaverRun.mvDownload')}
        </Button>
        <Button
          size="small"
          variant="outlined"
          onClick={onCollect}
          disabled={!currentRunId || mergedVideoCollecting}
        >
          {mergedVideoCollecting ? t('dreamweaverRun.mvArchiving') : t('dreamweaverRun.mvArchive')}
        </Button>
      </Stack>
      {mergedVideoCollectFeedback && (
        <Alert severity={mergedVideoCollectFeedback.type} sx={{ mt: 1 }}>
          {mergedVideoCollectFeedback.text}
        </Alert>
      )}
      {mergedVideoError && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {mergedVideoError}
        </Alert>
      )}
      {mergedVideoPreviewUrl && (
        <Box
          sx={{
            mt: 1,
            bgcolor: '#000', // sg-color-fixed: 视频播放器画布黑底（媒体数据色，双模恒黑）
            borderRadius: 2,
            overflow: 'hidden',
            ...(centeredPreview
              ? {
                  mx: 'auto',
                  width: '100%',
                  maxWidth: mergedVideoPreviewPortrait ? 360 : 720,
                }
              : {}),
          }}
        >
          <Box component="video" src={mergedVideoPreviewUrl} controls sx={{ width: '100%', display: 'block' }} />
        </Box>
      )}
    </>
  )
}
