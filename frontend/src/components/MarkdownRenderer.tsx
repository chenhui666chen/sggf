import type { ReactNode } from 'react'
import { Box, Divider, Paper, Typography } from '@mui/material'
import type { SxProps, Theme } from '@mui/material/styles'
import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import rehypeRaw from 'rehype-raw'
import remarkGfm from 'remark-gfm'
import { normalizeMarkdownContent } from '@/utils/normalizeMarkdownContent'

interface MarkdownRendererProps {
  content: string
}

type MarkdownContentSegment =
  | {
      type: 'markdown'
      content: string
    }
  | {
      type: 'details'
      open: boolean
      summary: string
      content: string
    }

const DETAILS_BLOCK_PATTERN = /<details(?<attrs>[^>]*)>(?<inner>[\s\S]*?)<\/details>/gi
const SUMMARY_PATTERN = /<summary>(?<summary>[\s\S]*?)<\/summary>/i

const detailsContainerSx: SxProps<Theme> = {
  my: 1.5,
  p: 1.5,
  bgcolor: 'grey.50',
  borderRadius: 1,
  border: '1px solid',
  borderColor: 'divider',
}

const detailsSummarySx: SxProps<Theme> = {
  cursor: 'pointer',
  fontWeight: 600,
  color: 'primary.main',
  py: 0.5,
  userSelect: 'none',
  '&:hover': {
    color: 'primary.dark',
  },
}

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
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
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
  hr: () => <Divider sx={{ my: 3 }} />,
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

function stripHtmlTags(value: string): string {
  return value.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
}

export function splitMarkdownContentSegments(content: string): MarkdownContentSegment[] {
  if (!content) {
    return []
  }

  const normalized = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const segments: MarkdownContentSegment[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  DETAILS_BLOCK_PATTERN.lastIndex = 0

  while ((match = DETAILS_BLOCK_PATTERN.exec(normalized)) !== null) {
    const matchStart = match.index ?? 0
    if (matchStart > lastIndex) {
      const markdownContent = normalized.slice(lastIndex, matchStart)
      if (markdownContent.trim()) {
        segments.push({
          type: 'markdown',
          content: markdownContent,
        })
      }
    }

    const attrs = match.groups?.attrs ?? ''
    const inner = match.groups?.inner ?? ''
    const summaryMatch = SUMMARY_PATTERN.exec(inner)
    const summary = stripHtmlTags(summaryMatch?.groups?.summary ?? '')
    const body = summaryMatch
      ? inner.slice((summaryMatch.index ?? 0) + summaryMatch[0].length).trim()
      : inner.trim()

    segments.push({
      type: 'details',
      open: /(?:^|\s)open(?:\s|=|$)/i.test(attrs),
      summary,
      content: body,
    })

    lastIndex = matchStart + match[0].length
  }

  if (lastIndex < normalized.length) {
    const markdownContent = normalized.slice(lastIndex)
    if (markdownContent.trim()) {
      segments.push({
        type: 'markdown',
        content: markdownContent,
      })
    }
  }

  return segments
}

function renderMarkdownBlock(content: string, key: string) {
  const cleanedContent = normalizeMarkdownContent(content)
  if (!cleanedContent) {
    return null
  }

  return (
    <ReactMarkdown
      key={key}
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      components={markdownComponents}
    >
      {cleanedContent}
    </ReactMarkdown>
  )
}

function renderMarkdownSegments(content: string, keyPrefix: string): ReactNode[] {
  return splitMarkdownContentSegments(content)
    .map((segment, index) => {
      const key = `${keyPrefix}-${index}`

      if (segment.type === 'markdown') {
        return renderMarkdownBlock(segment.content, key)
      }

      return (
        <Box component="details" key={key} open={segment.open} sx={detailsContainerSx}>
          <Box component="summary" sx={detailsSummarySx}>
            {segment.summary || '展开详情'}
          </Box>
          <Box sx={{ mt: 1 }}>
            {renderMarkdownSegments(segment.content, `${key}-content`)}
          </Box>
        </Box>
      )
    })
    .filter(Boolean)
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  if (!content) {
    return null
  }

  const segments = renderMarkdownSegments(content, 'markdown')
  if (segments.length === 0) {
    return null
  }

  return (
    <Box
      sx={{
        wordBreak: 'break-word',
        overflowWrap: 'break-word',
        '& > *:first-of-type': {
          mt: 0,
        },
        '& > *:last-child': {
          mb: 0,
        },
        '& details[open] > summary': {
          mb: 1,
          pb: 1,
          borderBottom: '1px solid',
          borderColor: 'divider',
        },
      }}
    >
      {segments}
    </Box>
  )
}
