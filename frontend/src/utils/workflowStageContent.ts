function formatStructuredContent(content: unknown): string {
  if (Array.isArray(content)) {
    return content
      .map((item) => (typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)))
      .join('\n\n')
  }

  if (content && typeof content === 'object') {
    return JSON.stringify(content, null, 2)
  }

  return String(content ?? '')
}

export function parseWorkflowStageContent(content: unknown): string {
  if (!content) {
    return ''
  }

  if (typeof content === 'string') {
    try {
      if (content.startsWith('"') || content.startsWith('[')) {
        return formatStructuredContent(JSON.parse(content))
      }
    } catch {
      return content
    }

    return content
  }

  return formatStructuredContent(content)
}
