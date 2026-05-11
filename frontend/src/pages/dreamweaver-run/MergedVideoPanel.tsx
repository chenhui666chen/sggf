import { Alert, Box, Button, Stack } from '@mui/material'

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
  return (
    <>
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
        <Button
          size="small"
          variant="outlined"
          onClick={onLoadPreview}
          disabled={!currentRunId || mergedVideoLoading}
        >
          {mergedVideoLoading ? '加载中…' : mergedVideoPreviewUrl ? '重新加载合成视频' : '加载合成视频预览'}
        </Button>
        <Button
          size="small"
          variant="contained"
          onClick={onDownload}
          disabled={!currentRunId || mergedVideoLoading}
        >
          下载合成视频
        </Button>
        <Button
          size="small"
          variant="outlined"
          onClick={onCollect}
          disabled={!currentRunId || mergedVideoCollecting}
        >
          {mergedVideoCollecting ? '归档中…' : '归档到用户中心'}
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
            bgcolor: '#000',
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
