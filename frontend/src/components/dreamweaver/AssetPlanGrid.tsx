import { useMemo } from 'react'
import {
  Box,
  Card,
  CardContent,
  Chip,
  Grid,
  Typography,
  Paper,
  Stack,
} from '@mui/material'
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import type { DreamweaverAssetPlanItem } from '@/types/dreamweaver'
import { LazyImage } from '@/hooks/useLazyImage'

interface AssetPlanGridProps {
  items: DreamweaverAssetPlanItem[]
  title?: string
  maxItems?: number
  onAssetClick?: (item: DreamweaverAssetPlanItem) => void
}

export function AssetPlanGrid({
  items,
  title,
  maxItems = 24,
  onAssetClick,
}: AssetPlanGridProps) {
  const displayItems = useMemo(() => items.slice(0, maxItems), [items, maxItems])
  const remaining = items.length - maxItems

  const summary = useMemo(() => {
    const total = items.length
    const done = items.filter((i) => i.status === 'done').length
    const planned = items.filter((i) => i.status === 'planned').length
    const processing = items.filter((i) => i.status === 'processing').length
    const images = items.filter((i) => i.kind === 'image').length
    const videos = items.filter((i) => i.kind === 'video').length
    return { total, done, planned, processing, images, videos }
  }, [items])

  if (!items.length) return null

  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      {title && (
        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
          {title}
        </Typography>
      )}
      <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 1 }}>
        <Chip size="small" label={`总计: ${summary.total}`} />
        <Chip size="small" label={`完成: ${summary.done}`} color={summary.done > 0 ? 'success' : 'default'} />
        {summary.processing > 0 && (
          <Chip size="small" label={`生成中: ${summary.processing}`} color="warning" />
        )}
        <Chip size="small" label={`图像: ${summary.images}`} variant="outlined" />
        <Chip size="small" label={`视频: ${summary.videos}`} variant="outlined" />
      </Stack>
      <Grid container spacing={1.5}>
        {displayItems.map((item) => (
          <Grid item key={item.id} xs={6} sm={4} md={3} lg={2}>
            <Card
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                cursor: onAssetClick ? 'pointer' : 'default',
                border: item.status === 'processing' ? '2px solid' : '1px solid',
                borderColor: item.status === 'processing' ? 'warning.main' : 'divider',
                opacity: item.status === 'planned' ? 0.7 : 1,
                transition: 'all 0.2s',
                '&:hover': onAssetClick
                  ? {
                      boxShadow: 2,
                      transform: 'translateY(-2px)',
                    }
                  : {},
              }}
              onClick={() => onAssetClick?.(item)}
            >
              <Box
                sx={{
                  position: 'relative',
                  paddingTop: '100%',
                  bgcolor: 'grey.100',
                  overflow: 'hidden',
                }}
              >
                {item.status === 'done' && item.uri ? (
                  <LazyImage
                    src={item.uri}
                    alt={item.label || item.id}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: '100%',
                      objectFit: 'cover',
                    }}
                    placeholder=""
                    fallback={
                      <Box
                        sx={{
                          position: 'absolute',
                          top: '50%',
                          left: '50%',
                          transform: 'translate(-50%, -50%)',
                        }}
                      >
                        {item.kind === 'video' ? (
                          <PlayArrowIcon sx={{ fontSize: 32, color: 'grey.400' }} />
                        ) : (
                          <PhotoCameraIcon sx={{ fontSize: 32, color: 'grey.400' }} />
                        )}
                      </Box>
                    }
                  />
                ) : item.status === 'processing' ? (
                  <Box
                    sx={{
                      position: 'absolute',
                      top: '50%',
                      left: '50%',
                      transform: 'translate(-50%, -50%)',
                      textAlign: 'center',
                    }}
                  >
                    <Box
                      sx={{
                        width: 24,
                        height: 24,
                        border: '2px solid',
                        borderColor: 'primary.main',
                        borderTopColor: 'transparent',
                        borderRadius: '50%',
                        animation: 'spin 1s linear infinite',
                        '@keyframes spin': {
                          '0%': { transform: 'rotate(0deg)' },
                          '100%': { transform: 'rotate(360deg)' },
                        },
                      }}
                    />
                  </Box>
                ) : (
                  <Box
                    sx={{
                      position: 'absolute',
                      top: '50%',
                      left: '50%',
                      transform: 'translate(-50%, -50%)',
                    }}
                  >
                    {item.kind === 'video' ? (
                      <PlayArrowIcon sx={{ fontSize: 32, color: 'grey.400' }} />
                    ) : (
                      <PhotoCameraIcon sx={{ fontSize: 32, color: 'grey.400' }} />
                    )}
                  </Box>
                )}
                {item.status === 'processing' && (
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 4,
                      right: 4,
                      bgcolor: 'warning.main',
                      color: 'white',
                      fontSize: '0.65rem',
                      px: 0.5,
                      py: 0.25,
                      borderRadius: 0.5,
                    }}
                  >
                    生成中
                  </Box>
                )}
                {item.status === 'done' && (
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 4,
                      right: 4,
                      bgcolor: 'success.main',
                      color: 'white',
                      fontSize: '0.65rem',
                      px: 0.5,
                      py: 0.25,
                      borderRadius: 0.5,
                    }}
                  >
                    完成
                  </Box>
                )}
                {item.kind === 'video' && (
                  <Box
                    sx={{
                      position: 'absolute',
                      bottom: 4,
                      left: 4,
                      bgcolor: 'rgba(0,0,0,0.6)',
                      color: 'white',
                      fontSize: '0.6rem',
                      px: 0.5,
                      borderRadius: 0.25,
                    }}
                  >
                    视频
                  </Box>
                )}
              </Box>
              <CardContent sx={{ p: 1, '&:last-child': { pb: 1 } }}>
                <Typography
                  variant="caption"
                  sx={{ fontWeight: 500, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                >
                  {item.label || item.id}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
                  {item.status === 'done' ? '已生成' : item.status === 'processing' ? '生成中...' : '待生成'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
      {remaining > 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          还有 {remaining} 个资产...
        </Typography>
      )}
    </Paper>
  )
}
