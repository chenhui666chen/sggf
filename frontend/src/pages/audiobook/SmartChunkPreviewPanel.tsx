import {
  Alert,
  Box,
  Chip,
  Divider,
  List,
  ListItem,
  Typography,
} from '@mui/material'

import type { SmartChunkPreviewResult } from './types'

interface SmartChunkPreviewPanelProps {
  preview: SmartChunkPreviewResult
  mutedTextColor?: string
  dangerTextColor?: string
}

const formatNumber = (value: number): string =>
  Number.isFinite(value) ? String(Math.round(value)) : '0'

const SmartChunkPreviewPanel = ({
  preview,
  mutedTextColor,
  dangerTextColor,
}: SmartChunkPreviewPanelProps) => {
  const changedSeverity = preview.changed ? 'warning' : 'success'
  const changedMessage = preview.changed
    ? `将从 ${preview.originalSegments} 段调整为 ${preview.chunkedSegments} 个合成块`
    : '当前片段长度处于安全范围'
  const visibleChunks = preview.chunks.slice(0, 5)
  const mutedColor = mutedTextColor || 'text.secondary'
  const dangerColor = dangerTextColor || 'error.main'

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Alert severity={preview.oversizedChunkCount > 0 ? 'error' : changedSeverity}>
        {changedMessage}
        {preview.oversizedChunkCount > 0 ? `，仍有 ${preview.oversizedChunkCount} 个块超过上限` : ''}
      </Alert>

      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        <Chip size="small" label={`总 token ${formatNumber(preview.totalTokens)}`} />
        <Chip size="small" label={`平均 ${formatNumber(preview.stats.avg_tokens_per_chunk)}`} />
        <Chip size="small" label={`最大 ${formatNumber(preview.stats.max_tokens_in_chunk)}`} />
        <Chip size="small" label={`最小 ${formatNumber(preview.stats.min_tokens_in_chunk)}`} />
      </Box>

      {visibleChunks.length > 0 && (
        <>
          <Divider sx={{ my: 0.5 }} />
          <List dense disablePadding>
            {visibleChunks.map((chunk, index) => {
              const estimatedTokens = typeof (chunk as { estimated_tokens?: unknown }).estimated_tokens === 'number'
                ? (chunk as { estimated_tokens: number }).estimated_tokens
                : 0
              const chunkText = String(chunk.text || '').trim()
              return (
                <ListItem
                  key={`${index}-${chunkText.slice(0, 12)}`}
                  disableGutters
                  sx={{ display: 'block', py: 0.75 }}
                >
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, mb: 0.25 }}>
                    <Typography variant="caption" sx={{ color: mutedColor }}>
                      块 {index + 1}
                    </Typography>
                    <Typography variant="caption" sx={{ color: estimatedTokens > 1800 ? dangerColor : mutedColor }}>
                      {formatNumber(estimatedTokens)} token
                    </Typography>
                  </Box>
                  <Typography
                    variant="body2"
                    sx={{
                      color: mutedColor,
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical',
                      overflow: 'hidden',
                    }}
                  >
                    {chunkText || '空片段'}
                  </Typography>
                </ListItem>
              )
            })}
          </List>
          {preview.chunks.length > visibleChunks.length && (
            <Typography variant="caption" sx={{ color: mutedColor }}>
              另有 {preview.chunks.length - visibleChunks.length} 个合成块
            </Typography>
          )}
        </>
      )}
    </Box>
  )
}

export default SmartChunkPreviewPanel
