/**
 * 格式化内容显示组件
 * 自动将 Markdown 格式的文本渲染为 HTML
 */
import React from 'react'
import { Box, SxProps, Theme } from '@mui/material'
import MarkdownRenderer from '../MarkdownRenderer'
import { normalizeMarkdownContent } from '../../utils/normalizeMarkdownContent'

interface FormattedContentProps {
  content: string
  sx?: SxProps<Theme>
  className?: string
}

/**
 * 格式化内容组件
 * 
 * 使用方式：
 * ```tsx
 * <FormattedContent content={aiGeneratedContent} />
 * ```
 */
export default function FormattedContent({ content, sx, className }: FormattedContentProps) {
  const normalizedContent = React.useMemo(() => {
    if (!content) return ''

    // 前端展示排除开发说明：移除全角括号及其中内容
    let text = normalizeMarkdownContent(content).replace(/（[^）]*）/g, '')

    text = text.replace(/&lt;details[^&]*&gt;[\s\S]*?&lt;\/details&gt;/gi, (match) =>
      match
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
    )

    return text
  }, [content])

  return (
    <Box
      className={className}
      sx={{
        '& h1, & h2, & h3': {
          fontWeight: 600,
          color: 'primary.main',
        },
        '& h1': {
          fontSize: '1.5rem',
          marginTop: '24px',
          marginBottom: '12px',
        },
        '& h2': {
          fontSize: '1.25rem',
          marginTop: '20px',
          marginBottom: '10px',
        },
        '& h3': {
          fontSize: '1.1rem',
          marginTop: '16px',
          marginBottom: '8px',
        },
        '& p': {
          margin: '12px 0',
          lineHeight: 1.6,
          color: 'text.primary',
        },
        '& ul, & ol': {
          margin: '8px 0',
          paddingLeft: '20px',
        },
        '& li': {
          marginBottom: '4px',
          lineHeight: 1.5,
        },
        '& hr': {
          border: 'none',
          borderTop: '1px solid',
          borderColor: 'divider',
          margin: '16px 0',
        },
        '& strong': {
          fontWeight: 600,
          color: 'error.main',
        },
        // 🌟 details/summary 标签样式（可展开/收起）
        '& details': {
          margin: '12px 0',
          padding: '8px 12px',
          backgroundColor: 'grey.50',
          borderRadius: 1,
          border: '1px solid',
          borderColor: 'divider',
        },
        '& summary': {
          cursor: 'pointer',
          fontWeight: 600,
          color: 'primary.main',
          padding: '4px 0',
          userSelect: 'none',
          '&:hover': {
            color: 'primary.dark',
          },
          '&::marker': {
            color: 'primary.main',
          },
        },
        '& details[open] > summary': {
          marginBottom: '8px',
          borderBottom: '1px solid',
          borderColor: 'divider',
          paddingBottom: '8px',
        },
        ...sx,
      }}
    >
      <MarkdownRenderer content={normalizedContent} />
    </Box>
  )
}

/**
 * 简化版：仅用于显示纯文本（保留换行）
 */
export function PlainTextContent({ content, sx, className }: FormattedContentProps) {
  return (
    <Box
      className={className}
      sx={{
        whiteSpace: 'pre-wrap',
        lineHeight: 1.6,
        fontFamily: 'inherit',
        ...sx,
      }}
    >
      {content}
    </Box>
  )
}

/**
 * 代码块样式：用于显示代码或结构化数据
 */
export function CodeBlockContent({ content, sx, className }: FormattedContentProps) {
  return (
    <Box
      className={className}
      sx={{
        whiteSpace: 'pre-wrap',
        lineHeight: 1.5,
        fontFamily: 'monospace',
        fontSize: '0.875rem',
        backgroundColor: 'grey.100',
        padding: 2,
        borderRadius: 1,
        overflow: 'auto',
        ...sx,
      }}
    >
      {content}
    </Box>
  )
}

