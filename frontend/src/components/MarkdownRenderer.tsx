import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Box, Typography, Divider, Paper } from '@mui/material'
import type { Components } from 'react-markdown'

interface MarkdownRendererProps {
  content: string
}

// 自定义 Markdown 组件样式
const markdownComponents: Components = {
  h1: ({ children }) => (
    <Typography
      variant="h4"
      component="h1"
      sx={{
        fontWeight: 700,
        mt: 4,
        mb: 2,
        pb: 1,
        borderBottom: '2px solid',
        borderColor: 'primary.main',
        color: 'primary.dark',
      }}
    >
      {children}
    </Typography>
  ),
  h2: ({ children }) => (
    <Typography
      variant="h5"
      component="h2"
      sx={{
        fontWeight: 600,
        mt: 3,
        mb: 1.5,
        pb: 0.5,
        borderBottom: '1px solid',
        borderColor: 'grey.300',
        color: 'text.primary',
      }}
    >
      {children}
    </Typography>
  ),
  h3: ({ children }) => (
    <Typography
      variant="h6"
      component="h3"
      sx={{
        fontWeight: 600,
        mt: 2.5,
        mb: 1,
        color: 'primary.main',
      }}
    >
      {children}
    </Typography>
  ),
  h4: ({ children }) => (
    <Typography
      variant="subtitle1"
      component="h4"
      sx={{
        fontWeight: 600,
        mt: 2,
        mb: 0.5,
        color: 'text.secondary',
      }}
    >
      {children}
    </Typography>
  ),
  p: ({ children }) => (
    <Typography
      component="p"
      sx={{
        my: 1.5,
        lineHeight: 1.8,
        fontSize: '1rem',
        color: 'text.primary',
        textAlign: 'justify',
      }}
    >
      {children}
    </Typography>
  ),
  ul: ({ children }) => (
    <Box
      component="ul"
      sx={{
        my: 1.5,
        pl: 3,
        '& li': {
          mb: 0.8,
          lineHeight: 1.7,
        },
      }}
    >
      {children}
    </Box>
  ),
  ol: ({ children }) => (
    <Box
      component="ol"
      sx={{
        my: 1.5,
        pl: 3,
        '& li': {
          mb: 0.8,
          lineHeight: 1.7,
        },
      }}
    >
      {children}
    </Box>
  ),
  li: ({ children }) => (
    <Box
      component="li"
      sx={{
        '&::marker': {
          color: 'primary.main',
          fontWeight: 600,
        },
      }}
    >
      {children}
    </Box>
  ),
  strong: ({ children }) => (
    <Box
      component="strong"
      sx={{
        fontWeight: 700,
        color: 'primary.dark',
      }}
    >
      {children}
    </Box>
  ),
  em: ({ children }) => (
    <Box
      component="em"
      sx={{
        fontStyle: 'italic',
        color: 'text.secondary',
      }}
    >
      {children}
    </Box>
  ),
  blockquote: ({ children }) => (
    <Paper
      elevation={0}
      sx={{
        my: 2,
        pl: 2,
        py: 1,
        borderLeft: '4px solid',
        borderColor: 'primary.light',
        bgcolor: 'grey.50',
        fontStyle: 'italic',
        '& p': {
          my: 0.5,
        },
      }}
    >
      {children}
    </Paper>
  ),
  hr: () => (
    <Divider sx={{ my: 3 }} />
  ),
  code: ({ children, className }) => {
    const isInline = !className
    if (isInline) {
      return (
        <Box
          component="code"
          sx={{
            px: 0.8,
            py: 0.2,
            mx: 0.3,
            borderRadius: 1,
            bgcolor: 'grey.100',
            color: 'error.dark',
            fontFamily: 'monospace',
            fontSize: '0.9em',
          }}
        >
          {children}
        </Box>
      )
    }
    return (
      <Paper
        component="pre"
        elevation={0}
        sx={{
          p: 2,
          my: 2,
          borderRadius: 2,
          bgcolor: 'grey.900',
          color: 'grey.100',
          overflow: 'auto',
          fontFamily: 'monospace',
          fontSize: '0.85rem',
          lineHeight: 1.6,
        }}
      >
        <code>{children}</code>
      </Paper>
    )
  },
  table: ({ children }) => (
    <Box
      component="table"
      sx={{
        width: '100%',
        my: 2,
        borderCollapse: 'collapse',
        '& th, & td': {
          border: '1px solid',
          borderColor: 'grey.300',
          p: 1.5,
          textAlign: 'left',
        },
        '& th': {
          bgcolor: 'grey.100',
          fontWeight: 600,
        },
        '& tr:nth-of-type(even)': {
          bgcolor: 'grey.50',
        },
      }}
    >
      {children}
    </Box>
  ),
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  if (!content) {
    return null
  }

  return (
    <Box
      sx={{
        '& > *:first-of-type': {
          mt: 0,
        },
        '& > *:last-child': {
          mb: 0,
        },
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </Box>
  )
}

