import { useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, Paper, Typography, Chip, Stack } from '@mui/material'
import FormattedContent from '@/components/common/FormattedContent'

interface StreamingTextBlockProps {
  title: string
  text: string
  done?: boolean
  maxHeight?: number
  showLength?: boolean
}

export function StreamingTextBlock({
  title,
  text,
  done = false,
  maxHeight = 300,
  showLength = true,
}: StreamingTextBlockProps) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const prevLengthRef = useRef(0)

  useEffect(() => {
    if (containerRef.current && text.length > prevLengthRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
    prevLengthRef.current = text.length
  }, [text])

  if (!text.trim() && done) return null

  return (
    <Paper variant="outlined" sx={{ mb: 1 }}>
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        sx={{ px: 1.5, py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}
      >
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
        <Stack direction="row" spacing={1} alignItems="center">
          {showLength && <Chip size="small" label={t('dreamweaverRun.streamCharCount', { count: text.length })} />}
          <Chip
            size="small"
            label={done ? t('dreamweaverRun.streamDone') : t('dreamweaverRun.streamGenerating')}
            color={done ? 'success' : 'warning'}
          />
        </Stack>
      </Stack>
      <Box
        ref={containerRef}
        sx={{
          p: 1.5,
          maxHeight,
          overflow: 'auto',
          bgcolor: 'grey.50',
        }}
      >
        {text.trim() ? (
          <Box sx={{ position: 'relative' }}>
            <FormattedContent content={text} />
            {!done && (
              <Box
                component="span"
                sx={{
                  display: 'inline-block',
                  width: 8,
                  height: 16,
                  bgcolor: 'primary.main',
                  ml: 0.5,
                  animation: 'blink 1s infinite',
                  '@keyframes blink': {
                    '0%, 50%': { opacity: 1 },
                    '51%, 100%': { opacity: 0 },
                  },
                }}
              />
            )}
          </Box>
        ) : (
          <Typography variant="body2" color="text.secondary">
            {t('dreamweaverRun.streamWaiting')}
          </Typography>
        )}
      </Box>
    </Paper>
  )
}
