/**
 * 大纲和人物扩展的辅助工具函数
 */

/**
 * 计算扩展进度百分比
 * @param currentIteration 当前迭代次数
 * @param maxIterations 最大迭代次数
 * @returns 进度百分比 (0-100)
 */
export function calculateProgress(currentIteration: number, maxIterations: number): number {
  return Math.min(Math.round((currentIteration / maxIterations) * 100), 100)
}

/**
 * 估算剩余时间
 * @param startTime 开始时间戳
 * @param currentIteration 当前迭代次数
 * @param totalIterations 总迭代次数
 * @returns 预计剩余秒数
 */
export function estimateRemainingTime(
  startTime: number,
  currentIteration: number,
  totalIterations: number
): number {
  if (currentIteration === 0) return 0
  
  const elapsedTime = Date.now() - startTime
  const avgTimePerIteration = elapsedTime / currentIteration
  const remainingIterations = totalIterations - currentIteration
  
  return Math.round((avgTimePerIteration * remainingIterations) / 1000) // 转换为秒
}

/**
 * 格式化剩余时间显示
 * @param seconds 剩余秒数
 * @returns 格式化的时间字符串
 */
export function formatRemainingTime(seconds: number): string {
  if (seconds < 60) {
    return `约 ${seconds} 秒`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    return `约 ${minutes} 分钟`
  } else {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `约 ${hours} 小时 ${minutes} 分钟`
  }
}

/**
 * 保存扩展历史记录
 * @param type 类型：outline 或 character
 * @param content 内容
 * @param count 数量（章节数或人物数）
 */
export function saveHistory(
  type: 'outline' | 'character',
  content: string,
  count: number
): { timestamp: number; content: string; chapterCount?: number; characterCount?: number } {
  const record = {
    timestamp: Date.now(),
    content,
    ...(type === 'outline' ? { chapterCount: count } : { characterCount: count })
  }
  
  const storageKey = `expansion_history_${type}`
  const history = getHistory(type)
  history.push(record)
  
  // 只保留最近20条记录
  if (history.length > 20) {
    history.shift()
  }
  
  localStorage.setItem(storageKey, JSON.stringify(history))
  return record
}

/**
 * 获取扩展历史记录
 * @param type 类型：outline 或 character
 * @returns 历史记录数组
 */
export function getHistory(type: 'outline' | 'character'): Array<any> {
  const storageKey = `expansion_history_${type}`
  const stored = localStorage.getItem(storageKey)
  return stored ? JSON.parse(stored) : []
}

/**
 * 清除历史记录
 * @param type 类型：outline 或 character
 */
export function clearHistory(type: 'outline' | 'character'): void {
  const storageKey = `expansion_history_${type}`
  localStorage.removeItem(storageKey)
}

/**
 * 导出为Markdown格式
 * @param content 内容
 * @param title 标题
 * @param metadata 元数据
 * @returns Markdown格式字符串
 */
export function exportToMarkdown(
  content: string,
  title: string,
  metadata?: { [key: string]: any }
): string {
  let markdown = `# ${title}\n\n`
  
  if (metadata) {
    markdown += `## 元信息\n\n`
    Object.entries(metadata).forEach(([key, value]) => {
      markdown += `- **${key}**: ${value}\n`
    })
    markdown += `\n`
  }
  
  markdown += `## 内容\n\n${content}\n`
  
  return markdown
}

/**
 * 下载文本文件
 * @param content 文件内容
 * @param filename 文件名
 * @param mimeType MIME类型
 */
export function downloadFile(
  content: string,
  filename: string,
  mimeType: string = 'text/plain'
): void {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/**
 * 导出章节分解为CSV格式（可用Excel打开）
 * @param chapterBreakdown 章节分解内容
 * @returns CSV格式字符串
 */
export function exportChapterBreakdownToCSV(chapterBreakdown: string): string {
  const lines = chapterBreakdown.split('\n')
  let csv = '章节编号,标题,主要内容,关键事件,涉及人物,人物发展\n'
  
  let currentChapter = ''
  let currentData: { [key: string]: string } = {}
  
  lines.forEach(line => {
    const trimmed = line.trim()
    
    // 匹配章节标题
    const chapterMatch = trimmed.match(/^第(\d+)章[：:]\s*(.+)/)
    if (chapterMatch) {
      // 保存上一章数据
      if (currentChapter && Object.keys(currentData).length > 0) {
        csv += `${currentChapter},${escapeCSV(currentData['title'] || '')},${escapeCSV(currentData['content'] || '')},${escapeCSV(currentData['events'] || '')},${escapeCSV(currentData['characters'] || '')},${escapeCSV(currentData['development'] || '')}\n`
      }
      
      // 开始新章
      currentChapter = chapterMatch[1]
      currentData = { title: chapterMatch[2] }
    }
    
    // 匹配内容项
    if (trimmed.startsWith('- 主要内容：') || trimmed.startsWith('-主要内容：')) {
      currentData['content'] = trimmed.replace(/^-\s*主要内容[：:]\s*/, '')
    } else if (trimmed.startsWith('- 关键事件：') || trimmed.startsWith('-关键事件：')) {
      currentData['events'] = trimmed.replace(/^-\s*关键事件[：:]\s*/, '')
    } else if (trimmed.startsWith('- 涉及人物：') || trimmed.startsWith('-涉及人物：')) {
      currentData['characters'] = trimmed.replace(/^-\s*涉及人物[：:]\s*/, '')
    } else if (trimmed.startsWith('- 人物发展：') || trimmed.startsWith('-人物发展：')) {
      currentData['development'] = trimmed.replace(/^-\s*人物发展[：:]\s*/, '')
    }
  })
  
  // 保存最后一章
  if (currentChapter && Object.keys(currentData).length > 0) {
    csv += `${currentChapter},${escapeCSV(currentData['title'] || '')},${escapeCSV(currentData['content'] || '')},${escapeCSV(currentData['events'] || '')},${escapeCSV(currentData['characters'] || '')},${escapeCSV(currentData['development'] || '')}\n`
  }
  
  return csv
}

/**
 * CSV转义函数
 */
function escapeCSV(str: string): string {
  if (!str) return ''
  // 如果包含逗号、引号或换行符，用双引号包围，并将双引号转义
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return `"${str.replace(/"/g, '""')}"`
  }
  return str
}
