import { Box, IconButton, Paper, Typography } from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'

interface CodeSnippetSectionWithCopyProps {
  title: string
  language: string
  code?: string
  onCopy?: () => void
  isCopied?: boolean
}

export function CodeSnippetSectionWithCopy({ title, language, code, onCopy, isCopied }: CodeSnippetSectionWithCopyProps) {
  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{title}</Typography>
        {code && onCopy && (
          <IconButton size="small" onClick={onCopy}>
            {isCopied ? <CheckCircleIcon fontSize="small" color="success" /> : <ContentCopyIcon fontSize="small" />}
          </IconButton>
        )}
      </Box>
      <Box
        sx={{
          p: 1.5,
          borderRadius: 2,
          backgroundColor: 'rgba(15,76,129,0.04)',
          fontFamily: 'monospace',
          fontSize: '0.85rem',
          whiteSpace: 'pre-wrap',
          overflow: 'auto',
          maxHeight: 300,
        }}
      >
        {code || '暂无代码'}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.8, display: 'block' }}>
        语言：{language}
      </Typography>
    </Paper>
  )
}
