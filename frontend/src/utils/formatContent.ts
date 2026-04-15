/**
 * 内容格式化工具
 * 用于将 AI 生成的内容（包含 Markdown 格式标记）转换为可读的 HTML
 */

/**
 * 将 Markdown 格式的文本转换为 HTML
 * 支持：
 * - 标题 (###)
 * - 加粗 (**)
 * - 列表 (-)
 * - 换行 (\n)
 * - 分隔线 (---)
 * - 星级评分 (⭐)
 */
export function formatMarkdownToHtml(content: string): string {
  if (!content) return ''

  let html = content
  const isBlockHtmlLine = (line: string): boolean => /^(<h\d\b|<hr\b|<(ul|ol|li)\b|<\/(ul|ol|li)>)/.test(line)
  const textHeadingPatterns = [
    /^【第[零一二三四五六七八九十百千万两\d]+[章节卷回幕篇]】(?:\s*\S.*)?$/,
    /^(?:第[零一二三四五六七八九十百千万两\d]+[章节卷回幕篇]|卷[零一二三四五六七八九十百千万两\d]+)(?:[：:]\s*|\s{1,2})\S.+$/,
  ]
  const isStandaloneTextHeadingLine = (line: string): boolean =>
    textHeadingPatterns.some((pattern) => pattern.test(line))
  const buildStandaloneTextHeading = (line: string): string =>
    `<h3 style="font-size: 1.1rem; font-weight: 600; margin: 16px 0 8px 0; color: inherit;">${line}</h3>`

  // 0. 处理转义的换行符（将 \n 转换为实际换行符）
  html = html.replace(/\\n/g, '\n')

  // 1. 转义 HTML 特殊字符（防止 XSS）
  html = html
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  
  // 2. 处理标题 (### 标题)
  html = html.replace(/^###\s+(.+)$/gm, '<h3 style="font-size: 1.1rem; font-weight: 600; margin: 16px 0 8px 0; color: #1976d2;">$1</h3>')
  html = html.replace(/^##\s+(.+)$/gm, '<h2 style="font-size: 1.25rem; font-weight: 600; margin: 20px 0 10px 0; color: #1565c0;">$1</h2>')
  html = html.replace(/^#\s+(.+)$/gm, '<h1 style="font-size: 1.5rem; font-weight: 700; margin: 24px 0 12px 0; color: #0d47a1;">$1</h1>')
  
  // 3. 处理加粗 (**文本**)
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong style="font-weight: 600; color: #d32f2f;">$1</strong>')
  
  // 4. 处理分隔线 (---)
  html = html.replace(/^---+$/gm, '<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 16px 0;" />')
  
  // 5. 处理列表项 (- 项目 或 1. 项目)
  html = html.replace(/^-\s+(.+)$/gm, '<li style="margin-left: 20px; margin-bottom: 4px;">$1</li>')
  html = html.replace(/^\d+\.\s+(.+)$/gm, '<li style="margin-left: 20px; margin-bottom: 4px; list-style-type: decimal;">$1</li>')
  
  // 6. 将连续的 <li> 包装在 <ul> 或 <ol> 中
  html = html.replace(/(<li[^>]*>.*?<\/li>\s*)+/gs, (match) => {
    if (match.includes('list-style-type: decimal')) {
      return `<ol style="margin: 8px 0; padding-left: 20px;">${match}</ol>`
    }
    return `<ul style="margin: 8px 0; padding-left: 20px;">${match}</ul>`
  })
  
  // 7. 处理星级评分 (⭐ 或 星星emoji)
  html = html.replace(/⭐/g, '<span style="color: #ffa726;">⭐</span>')
  
  // 8. 处理段落（连续的非空行）
  const lines = html.split('\n')
  const paragraphs: string[] = []
  let currentParagraph: string[] = []
  
  for (const line of lines) {
    const trimmedLine = line.trim()
    
    // 如果是空行，结束当前段落
    if (!trimmedLine) {
      if (currentParagraph.length > 0) {
        paragraphs.push(currentParagraph.join('<br />'))
        currentParagraph = []
      }
      continue
    }

    if (isStandaloneTextHeadingLine(trimmedLine)) {
      if (currentParagraph.length > 0) {
        paragraphs.push(currentParagraph.join('<br />'))
        currentParagraph = []
      }
      paragraphs.push(buildStandaloneTextHeading(trimmedLine))
      continue
    }
    
    // 如果是标题、列表、分隔线等特殊元素，单独成段
    if (isBlockHtmlLine(trimmedLine)) {
      if (currentParagraph.length > 0) {
        paragraphs.push(currentParagraph.join('<br />'))
        currentParagraph = []
      }
      paragraphs.push(trimmedLine)
    } else {
      currentParagraph.push(trimmedLine)
    }
  }
  
  // 处理最后一个段落
  if (currentParagraph.length > 0) {
    paragraphs.push(currentParagraph.join('<br />'))
  }
  
  // 9. 将段落包装在 <p> 标签中
  html = paragraphs
    .map((p) => {
      // 如果已经是 HTML 标签，不包装
      if (isBlockHtmlLine(p)) {
        return p
      }
      return `<p style="margin: 12px 0; line-height: 1.6;">${p}</p>`
    })
    .join('\n')
  
  return html
}

/**
 * 简化版：仅处理换行和基本格式
 * 用于简单的文本显示
 */
export function formatSimpleText(content: string): string {
  if (!content) return ''

  return content
    .replace(/\\n/g, '\n')       // 处理转义的换行符
    .replace(/\n\n+/g, '\n\n')  // 多个空行合并为两个
    .replace(/\n/g, '<br />')    // 换行转换为 <br />
}

/**
 * 检测内容是否包含 Markdown 格式
 */
export function hasMarkdownFormat(content: string): boolean {
  if (!content) return false
  
  return (
    /^#{1,6}\s+/m.test(content) ||
    content.includes('**') ||
    content.includes('---') ||
    /^-\s+/m.test(content) ||
    /^\d+\.\s+/m.test(content)
  )
}

/**
 * 智能格式化：自动检测并选择合适的格式化方式
 */
export function smartFormat(content: string): string {
  if (!content) return ''
  
  if (hasMarkdownFormat(content)) {
    return formatMarkdownToHtml(content)
  }
  
  return formatSimpleText(content)
}

