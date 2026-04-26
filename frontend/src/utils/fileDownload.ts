export function downloadTextFile(options: {
  content: string
  filename: string
  mimeType?: string
}): void {
  const {
    content,
    filename,
    mimeType = 'text/plain',
  } = options

  if (typeof document === 'undefined' || typeof URL === 'undefined') {
    throw new Error('当前环境不支持文件下载')
  }

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
