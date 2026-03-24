/**
 * 拆书工具 API 服务
 */
import axios from 'axios'

const RAW_API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

function normalizeApiBaseUrl(baseURL: string): string {
  return baseURL === '/api' ? '' : baseURL
}

// 创建专用的 axios 实例
const bookParserClient = axios.create({
  baseURL: normalizeApiBaseUrl(RAW_API_URL),
  timeout: 300000, // 5分钟超时（AI分析可能较慢）
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
bookParserClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

// 响应拦截器
bookParserClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// ==================== 类型定义 ====================

export interface BookSource {
  id: number
  title: string
  author: string | null
  genre: string | null
  description: string | null
  source_type: string
  status: string
  parse_progress: number
  total_words: number
  total_chapters: number
  total_volumes: number
  created_at: string
  imported_project_id: number | null
}

export interface BookChapter {
  id: number
  chapter_number: number
  title: string
  word_count: number
  chapter_type: string
  volume_number: number | null
  volume_title: string | null
  summary: string | null
}

export interface BookChapterDetail {
  chapter_number: number
  title: string
  content: string
  word_count: number
  summary: string | null
  key_events: string[]
  appearing_characters: string[]
  outline_data: Record<string, any>
}

export interface BookAnalysis {
  id: number
  analysis_type: string
  content: Record<string, any>
  confidence: number
  completeness: number
  created_at: string
}

export interface ParseStatus {
  status: string
  progress: number
  message: string
  chapters_count: number | null
  error: string | null
}

export interface StructurePreview {
  book_id: number
  title: string
  structure: {
    detected_chapters: number
    detected_volumes: number
    detected_special: number
    main_pattern: string | null
    sample_titles: string[]
    has_structure: boolean
    estimated_total_words: number
  }
}

// ==================== API 方法 ====================

/**
 * 上传文本内容
 */
export async function uploadText(data: {
  title: string
  content: string
  author?: string
  genre?: string
  description?: string
}): Promise<BookSource> {
  const response = await bookParserClient.post('/api/v1/book-parser/upload-text', data)
  return response.data
}

/**
 * 上传文件
 */
export async function uploadFile(
  file: File,
  title?: string,
  author?: string,
  genre?: string
): Promise<BookSource> {
  const formData = new FormData()
  formData.append('file', file)
  if (title) formData.append('title', title)
  if (author) formData.append('author', author)
  if (genre) formData.append('genre', genre)

  const response = await bookParserClient.post('/api/v1/book-parser/upload-file', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

/**
 * 获取书籍列表
 */
export async function getBookList(): Promise<BookSource[]> {
  const response = await bookParserClient.get('/api/v1/book-parser/list')
  return response.data
}

/**
 * 获取书籍详情
 */
export async function getBook(bookId: number): Promise<BookSource> {
  const response = await bookParserClient.get(`/api/v1/book-parser/${bookId}`)
  return response.data
}

/**
 * 获取书籍章节列表
 */
export async function getBookChapters(bookId: number): Promise<BookChapter[]> {
  const response = await bookParserClient.get(`/api/v1/book-parser/${bookId}/chapters`)
  return response.data
}

/**
 * 获取章节内容
 */
export async function getChapterContent(
  bookId: number,
  chapterNumber: number
): Promise<BookChapterDetail> {
  const response = await bookParserClient.get(
    `/api/v1/book-parser/${bookId}/chapter/${chapterNumber}/content`
  )
  return response.data
}

/**
 * 获取书籍分析结果
 */
export async function getBookAnalyses(bookId: number): Promise<BookAnalysis[]> {
  const response = await bookParserClient.get(`/api/v1/book-parser/${bookId}/analyses`)
  return response.data
}

/**
 * 执行章节切分（异步）
 */
export async function parseBook(bookId: number): Promise<{ message: string; book_id: number; status: string }> {
  const response = await bookParserClient.post(`/api/v1/book-parser/${bookId}/parse`)
  return response.data
}

/**
 * 执行AI分析（异步）
 */
export async function analyzeBook(bookId: number): Promise<{ message: string; book_id: number; status: string }> {
  const response = await bookParserClient.post(`/api/v1/book-parser/${bookId}/analyze`)
  return response.data
}

/**
 * 获取解析/分析状态
 */
export async function getParseStatus(bookId: number): Promise<ParseStatus> {
  const response = await bookParserClient.get(`/api/v1/book-parser/${bookId}/status`)
  return response.data
}

/**
 * 预览书籍结构
 */
export async function previewStructure(bookId: number): Promise<StructurePreview> {
  const response = await bookParserClient.get(`/api/v1/book-parser/${bookId}/preview`)
  return response.data
}

/**
 * 删除书籍
 */
export async function deleteBook(bookId: number): Promise<{ message: string; book_id: number }> {
  const response = await bookParserClient.delete(`/api/v1/book-parser/${bookId}`)
  return response.data
}

/**
 * 轮询任务状态
 */
export function pollStatus(
  bookId: number,
  onProgress: (status: ParseStatus) => void,
  onComplete: (status: ParseStatus) => void,
  onError: (error: Error) => void,
  interval: number = 2000
): () => void {
  let stopped = false

  const poll = async () => {
    if (stopped) return

    try {
      const status = await getParseStatus(bookId)
      onProgress(status)

      if (status.status === 'completed' || status.status === 'chapters_done') {
        onComplete(status)
        return
      }

      if (status.status === 'failed') {
        onError(new Error(status.error || '任务失败'))
        return
      }

      // 继续轮询
      setTimeout(poll, interval)
    } catch (error) {
      onError(error as Error)
    }
  }

  poll()

  // 返回停止函数
  return () => {
    stopped = true
  }
}

/**
 * 导入预览信息
 */
export interface ImportPreview {
  book: {
    id: number
    title: string
    author: string | null
    total_words: number
    total_chapters: number
  }
  analyses: Array<{
    type: string
    type_name: string
    confidence: number
    item_count: number
  }>
  import_options: {
    characters: boolean
    worldview: boolean
    plot: boolean
    concepts: boolean
  }
}

/**
 * 导入请求
 */
export interface ImportRequest {
  project_title?: string
  import_settings?: boolean
  import_characters?: boolean
  import_chapters?: boolean  // 🆕 导入章节内容
  start_from_chapter?: number
}

/**
 * 导入结果
 */
export interface ImportResult {
  message: string
  project_id: number
  project_title: string
}

/**
 * 获取导入预览
 */
export async function getImportPreview(bookId: number): Promise<ImportPreview> {
  const response = await bookParserClient.get(`/api/v1/book-parser/${bookId}/import-preview`)
  return response.data
}

/**
 * 导入书籍为项目
 */
export async function importToProject(
  bookId: number,
  options: ImportRequest = {}
): Promise<ImportResult> {
  const response = await bookParserClient.post(`/api/v1/book-parser/${bookId}/import`, options)
  return response.data
}

/**
 * 重置导入状态（允许重新导入）
 */
export async function resetImportStatus(
  bookId: number
): Promise<{ message: string; book_id: number; title: string }> {
  const response = await bookParserClient.delete(`/api/v1/book-parser/${bookId}/import`)
  return response.data
}

// 导出默认对象
export default {
  uploadText,
  uploadFile,
  getBookList,
  getBook,
  getBookChapters,
  getChapterContent,
  getBookAnalyses,
  parseBook,
  analyzeBook,
  getParseStatus,
  previewStructure,
  deleteBook,
  pollStatus,
  getImportPreview,
  importToProject,
  resetImportStatus,
}
