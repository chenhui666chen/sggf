import axios, { AxiosInstance, AxiosError } from 'axios'

// 在开发环境中直接连接到后端，不使用Vite代理
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const DREAMWEAVER_SCHEMA_VERSION = '0.1.0'

type DreamweaverQualityMode = 'quality' | 'cost'

interface DreamweaverRunOptions {
  quality_mode?: DreamweaverQualityMode
  qc_allow_fail?: boolean
  smart_tuning?: boolean
  ab_variant?: string
  video_require_confirmation?: boolean
  prompt_review_required?: boolean
  style_preset?: string
  image_ratio?: string
  image_resolution?: string
}

interface DreamweaverProjectLockedGenerationConfig {
  locked: boolean
  style_preset: string
  image_ratio: string
  image_resolution: string
  source_run_id?: string | null
}

interface DreamweaverLibraryApproveRequest {
  approve_all?: boolean
  roles?: string[]
  approved?: boolean
}

interface DreamweaverLibraryRegenerateRequest {
  role: string
  run_id?: string
  prompt?: string
  style_preset?: string
  image_ratio?: string
  image_resolution?: string
  prefer_image_edit?: boolean
  prefer_view_chain_edit_base?: boolean
}

interface DreamweaverLibraryPromptSuggestRequest {
  role: string
  run_id?: string
  prompt?: string
  style_preset?: string
  image_ratio?: string
  image_resolution?: string
  mode?: 'template' | 'ai'
  prefer_view_chain_seed?: boolean
}

interface DreamweaverLibraryPromptSuggestResponse {
  role: string
  style_preset: string
  image_ratio: string
  prompt: string
  negative_prompt: string
  meta?: Record<string, any>
}

interface DreamweaverProjectGeneratedDeleteResponse {
  project_id: number
  deleted_runs: string[]
  skipped_runs: string[]
  deleted_library_assets: number
  deleted_library_dir: boolean
  deleted_library_anchor_projects: number
  library_skipped: boolean
  library_skip_reason?: string | null
  failed_paths: string[]
  failed_runs: Array<{ run_id: string; error: string }>
}

interface DreamweaverScriptUpdateRequest {
  script_text: string
}

interface DreamweaverScriptApproveRequest {
  approved: boolean
}

interface DreamweaverPromptReviewApproveRequest {
  approved: boolean
}

interface DreamweaverShotVideoPromptUpdateRequest {
  prompt?: string | null
}

interface DreamweaverRestartRequest {
  start_state: string
  reset_policy?: string
  qc_allow_fail?: boolean
  smart_tuning?: boolean
  shot_ids?: string[]
  cam_idxs?: number[]
  asset_roles?: string[]
}

interface DreamweaverVideoJobConfirmAsyncResponse {
  run_id: string
  status: 'queued' | 'blocked' | 'noop'
  task_id?: string | null
  message?: string | null
  video_clip_jobs?: any[] | null
}

interface DreamweaverVideoJobsRebuildResponse {
  run_id: string
  video_clip_jobs: any[]
}

function extractDetailMessage(detail: any): string | null {
  if (!detail) return null
  if (typeof detail === 'string') return detail.trim() || null
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as any
    if (first && typeof first === 'object') {
      const msg = typeof first.msg === 'string' ? first.msg : typeof first.message === 'string' ? first.message : null
      return msg?.trim() || null
    }
    return null
  }
  if (typeof detail === 'object') {
    if (typeof (detail as any).message === 'string') {
      const message = String((detail as any).message || '').trim()
      const modelErrorRaw = (detail as any).model_error
      if (typeof modelErrorRaw === 'string') {
        const modelError = modelErrorRaw.trim()
        if (modelError) {
          // 限制长度，避免将超长供应商报文直接塞满 UI
          const clipped = modelError.length > 240 ? `${modelError.slice(0, 240)}...` : modelError
          return `${message}（详情：${clipped}）`
        }
      }
      return message || null
    }
    if (typeof (detail as any).error === 'string') return String((detail as any).error || '').trim() || null
  }
  return null
}

function extractErrorMessageFromResponseData(data: any): string | null {
  if (!data) return null
  if (typeof data === 'string') return data.trim() || null
  if (typeof data === 'object') {
    const detailMsg = extractDetailMessage((data as any).detail)
    if (detailMsg) return detailMsg
    if (typeof (data as any).message === 'string') return String((data as any).message || '').trim() || null
    if (typeof (data as any).error === 'string') return String((data as any).error || '').trim() || null
  }
  return null
}

export async function extractApiErrorMessage(error: unknown, fallback: string = '请求失败'): Promise<string> {
  try {
    if (axios.isAxiosError(error)) {
      const responseData = (error as AxiosError).response?.data as any
      if (responseData instanceof Blob) {
        try {
          const text = await responseData.text()
          if (text && text.trim()) {
            try {
              const parsed = JSON.parse(text)
              return extractErrorMessageFromResponseData(parsed) || text.trim() || fallback
            } catch {
              return text.trim() || fallback
            }
          }
        } catch {
          // ignore
        }
        return fallback
      }
      return extractErrorMessageFromResponseData(responseData) || (error as AxiosError).message || fallback
    }

    if (typeof error === 'string') return error.trim() || fallback
    if (error && typeof error === 'object' && typeof (error as any).message === 'string') {
      return String((error as any).message || '').trim() || fallback
    }

    return fallback
  } catch {
    return fallback
  }
}

class ApiClient {
  public client: AxiosInstance

  constructor() {
    // 使用环境变量或默认值
    // 如果 API_URL 是 /api，则设置为空字符串，因为 API 路径已经包含了 /api
    let baseURL = API_URL
    if (baseURL === '/api') {
      baseURL = ''
    }

    this.client = axios.create({
      baseURL: baseURL,
      timeout: 120000, // ✅ 增加到120秒，防止大数据传输超时
      headers: {
        'Content-Type': 'application/json',
      },
      // ✅ 禁用自动重试，避免重复请求
      maxRedirects: 0,
    })

    console.log('🔧 ApiClient初始化, baseURL:', baseURL)

    // 请求拦截器
    this.client.interceptors.request.use((config) => {
      const token = localStorage.getItem('access_token')
      if (token) {
        // 确保headers对象存在
        if (!config.headers) {
          config.headers = {} as any
        }
        // 设置Authorization头
        config.headers['Authorization'] = `Bearer ${token}`
      }
      return config
    })

    // 响应拦截器
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.response?.status === 401) {
          localStorage.removeItem('access_token')
          window.location.href = '/login'
        }
        return Promise.reject(error)
      }
    )
  }

  // 认证API
  register(data: { username: string; email: string; password: string; full_name?: string }) {
    return this.client.post('/api/v1/auth/register', data)
  }

  login(data: { username: string; password: string }) {
    return this.client.post('/api/v1/auth/login', data)
  }

  logout() {
    return this.client.post('/api/v1/auth/logout')
  }

  getCurrentUser() {
    return this.client.get('/api/v1/auth/me')
  }

  changePassword(data: { old_password: string; new_password: string }) {
    return this.client.post('/api/v1/auth/change-password', data)
  }

  alipayCallback(code: string) {
    return this.client.post('/api/v1/auth/alipay/callback', { code })
  }

  wechatCallback(code: string) {
    return this.client.post('/api/v1/auth/wechat/callback', { code })
  }

  // 项目API
  getProjects() {
    return this.client.get('/api/v1/projects')
  }

  createProject(data: { title: string; description?: string; genre?: string }) {
    return this.client.post('/api/v1/projects', data)
  }

  getProject(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}`)
  }

  updateProject(projectId: number, data: any) {
    return this.client.put(`/api/v1/projects/${projectId}`, data)
  }

  deleteProject(projectId: number) {
    return this.client.delete(`/api/v1/projects/${projectId}`)
  }

  getProjectAudioConfig(projectId: number, ttsModel?: string) {
    return this.client.get(`/api/v1/projects/${projectId}/audio-config`, {
      params: ttsModel ? { tts_model: ttsModel } : undefined,
    })
  }

  updateProjectAudioConfig(projectId: number, data: any, ttsModel?: string) {
    return this.client.put(`/api/v1/projects/${projectId}/audio-config`, data, {
      params: ttsModel ? { tts_model: ttsModel } : undefined,
    })
  }

  autoAssignProjectAudioVoices(projectId: number, ttsModel?: string) {
    return this.client.post(
      `/api/v1/projects/${projectId}/audio-config/auto-voices`,
      null,
      {
        params: ttsModel ? { tts_model: ttsModel } : undefined,
      },
    )
  }

  // 章节API
  getChapters(projectId: number, sortOrder: 'asc' | 'desc' = 'asc') {
    return this.client.get(`/api/v1/projects/${projectId}/chapters?sort_order=${sortOrder}`)
  }

  createChapter(projectId: number, data: any) {
    // 使用正确的端点格式：/api/v1/projects/{projectId}/chapters
    return this.client.post(`/api/v1/projects/${projectId}/chapters`, data)
  }

  getChapter(chapterId: number) {
    return this.client.get(`/api/v1/chapters/${chapterId}`)
  }

  updateChapter(chapterId: number, data: any) {
    return this.client.put(`/api/v1/chapters/${chapterId}`, data)
  }

  autoSaveChapter(chapterId: number, data: any) {
    return this.client.post(`/api/v1/chapters/${chapterId}/auto-save`, data)
  }

  deleteChapter(chapterId: number, data?: { delete_reason?: string; delete_files?: boolean }) {
    return this.client.delete(`/api/v1/chapters/${chapterId}`, { data })
  }

  restoreChapter(chapterId: number) {
    return this.client.post(`/api/v1/chapters/${chapterId}/restore`)
  }

  getDeletedChapters(projectId: number) {
    return this.client.get(`/api/v1/chapters/deleted`, { params: { project_id: projectId } })
  }

  // 设定管理API
  getSettingCollections(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/setting-collections`)
  }

  createSettingCollection(projectId: number, data: any) {
    return this.client.post(`/api/v1/projects/${projectId}/setting-collections`, data)
  }

  updateSettingCollection(collectionId: number, data: any) {
    return this.client.put(`/api/v1/setting-collections/${collectionId}`, data)
  }

  deleteSettingCollection(collectionId: number) {
    return this.client.delete(`/api/v1/setting-collections/${collectionId}`)
  }

  getSettingItems(collectionId: number) {
    return this.client.get(`/api/v1/setting-collections/${collectionId}/items`)
  }

  createSettingItem(collectionId: number, data: any) {
    return this.client.post(`/api/v1/setting-collections/${collectionId}/items`, data)
  }

  updateSettingItem(itemId: number, data: any) {
    return this.client.put(`/api/v1/setting-items/${itemId}`, data)
  }

  moveSettingItem(itemId: number, targetCollectionId: number) {
    return this.client.post(`/api/v1/setting-items/${itemId}/move`, { target_collection_id: targetCollectionId })
  }

  deleteSettingItem(itemId: number) {
    return this.client.delete(`/api/v1/setting-items/${itemId}`)
  }

  reorderSettingItems(collectionId: number, items: { id: number; order: number }[]) {
    return this.client.patch(`/api/v1/setting-collections/${collectionId}/items/reorder`, {
      items,
    })
  }

  getSettingItemsByPath(collectionId: number, prefix?: string, maxDepth?: number) {
    const params: any = {}
    if (prefix) params.prefix = prefix
    if (maxDepth != null) params.max_depth = maxDepth
    return this.client.get(`/api/v1/setting-collections/${collectionId}/items/by-path`, { params })
  }

  getSettingItemsTree(collectionId: number) {
    return this.client.get(`/api/v1/setting-collections/${collectionId}/items/tree`)
  }

  getGraphEdgesForItem(itemId: number, direction: 'both' | 'out' | 'in' = 'both') {
    return this.client.get(`/api/v1/setting-items/${itemId}/graph-edges`, { params: { direction } })
  }

  createGraphEdge(payload: { source_item_id: number; target_item_id: number; relation_type: string; confidence?: number; auto_extracted?: boolean }) {
    return this.client.post(`/api/v1/graph-edges`, payload)
  }

  deleteGraphEdge(edgeId: number) {
    return this.client.delete(`/api/v1/graph-edges/${edgeId}`)
  }

  bulkMoveSettingItems(collectionId: number, payload: { item_ids: number[]; target_collection_id?: number; new_parent_path?: string }) {
    return this.client.post(`/api/v1/setting-collections/${collectionId}/items/bulk-move`, payload)
  }

  setParentForItem(itemId: number, newParentPath: string) {
    return this.client.post(`/api/v1/setting-items/${itemId}/set-parent`, { new_parent_path: newParentPath })
  }

  reorderUnderParent(collectionId: number, parentPath: string, orderedIds: number[]) {
    return this.client.patch(`/api/v1/setting-collections/${collectionId}/items/reorder-under-parent`, {
      parent_path: parentPath,
      ordered_ids: orderedIds,
    })
  }

  // 设定模板与摘要
  getSettingTemplates() {
    return this.client.get('/api/v1/setting-templates')
  }

  applySettingTemplate(projectId: number, payload: { template_key: string; clear_existing?: boolean }) {
    return this.client.post(`/api/v1/projects/${projectId}/setting-templates/apply`, payload)
  }

  getSettingsSummary(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/settings-summary`)
  }

  // 设定自动合并与冲突检测
  autoMergeSettings(projectId: number) {
    return this.client.post(`/api/v1/projects/${projectId}/auto-merge-settings`)
  }

  detectConflicts(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/detect-conflicts`)
  }

  getSettingRecommendations(projectId: number, category?: string, limit: number = 10) {
    const params: any = { limit }
    if (category) params.category = category
    return this.client.get(`/api/v1/projects/${projectId}/setting-recommendations`, { params })
  }

  rollbackSettingItem(itemId: number, snapshotIndex: number) {
    return this.client.post(`/api/v1/setting-items/${itemId}/rollback`, { snapshot_index: snapshotIndex })
  }

  // 评审API
  createReview(chapterId: number, data: any) {
    return this.client.post(`/api/v1/chapters/${chapterId}/review`, data)
  }

  getReview(chapterId: number) {
    return this.client.get(`/api/v1/chapters/${chapterId}/review`)
  }

  updateReview(chapterId: number, data: any) {
    return this.client.put(`/api/v1/chapters/${chapterId}/review`, data)
  }

  deleteReview(chapterId: number) {
    return this.client.delete(`/api/v1/chapters/${chapterId}/review`)
  }

  previewTTS(payload: { text: string; voice_id: string; volume?: number; speed?: number; pitch?: number; model?: string }) {
    return this.client.post('/api/v1/audiobook/tts/preview', payload, { responseType: 'blob' })
  }

  previewScriptSegmentAudio(
    audiobookProjectId: number,
    chapterId: number,
    payload: { segment: Record<string, any>; tts_model?: string; preview_type?: string }
  ) {
    return this.client.post(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/segments/preview`,
      payload,
      { responseType: 'blob' }
    )
  }

  getTtsVoices(model?: string) {
    return this.client.get('/api/v1/audiobook/tts/voices', {
      params: model ? { model } : undefined,
    })
  }

  createCosyVoiceV3PlusClone(payload: { name: string; url: string }) {
    return this.client.post('/api/v1/audiobook/tts/voices/cosyvoice-v3-plus/clones', payload)
  }

  deleteCosyVoiceV3PlusClone(voiceId: string) {
    return this.client.delete(
      `/api/v1/audiobook/tts/voices/cosyvoice-v3-plus/clones/${encodeURIComponent(voiceId)}`
    )
  }

  uploadCosyVoiceV3PlusCloneSample(file: File) {
    const form = new FormData()
    form.append('file', file)
    return this.client.post('/api/v1/audiobook/tts/voices/cosyvoice-v3-plus/clones/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  }

  // 角色管理API
  getCharacters(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/characters`)
  }

  createCharacter(projectId: number, data: any) {
    return this.client.post(`/api/v1/projects/${projectId}/characters`, data)
  }

  getCharacter(characterId: number) {
    return this.client.get(`/api/v1/characters/${characterId}`)
  }

  updateCharacter(characterId: number, data: any) {
    return this.client.put(`/api/v1/characters/${characterId}`, data)
  }

  deleteCharacter(characterId: number) {
    return this.client.delete(`/api/v1/characters/${characterId}`)
  }

  // 角色功法管理API
  getCharacterTechniques(characterId: number) {
    return this.client.get(`/api/v1/characters/${characterId}/techniques`)
  }

  updateCharacterTechniques(characterId: number, data: any) {
    return this.client.put(`/api/v1/characters/${characterId}/techniques`, data)
  }

  getProjectTechniques(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/techniques`)
  }

  // 有声书 API
  getAudiobookProjectsByProject(projectId: number, params?: { include_chapter_audios?: boolean }) {
    return this.client.get(`/api/v1/audiobook/projects/by-project/${projectId}`, { params })
  }

  getAudiobookProject(audiobookProjectId: number) {
    return this.client.get(`/api/v1/audiobook/projects/${audiobookProjectId}`)
  }

  deleteAudiobookProject(audiobookProjectId: number, data?: { delete_reason?: string; delete_files?: boolean }) {
    return this.client.delete(`/api/v1/audiobook/projects/${audiobookProjectId}`, { data })
  }

  deleteChapterAudio(chapterAudioId: number, data?: { delete_reason?: string; delete_files?: boolean }) {
    return this.client.delete(`/api/v1/audiobook/chapter-audios/${chapterAudioId}`, { data })
  }

  restoreAudiobookProject(audiobookProjectId: number) {
    return this.client.post(`/api/v1/audiobook/projects/${audiobookProjectId}/restore`)
  }

  restoreChapterAudio(chapterAudioId: number) {
    return this.client.post(`/api/v1/audiobook/chapter-audios/${chapterAudioId}/restore`)
  }

  listDeletedProjects() {
    return this.client.get('/api/v1/audiobook/projects/deleted')
  }

  createAudiobookProject(payload: {
    project_id: number
    chapter_ids: number[]
    tts_provider?: string
    enable_cache?: boolean
    voice_config?: any[]
    tts_model?: string
    generation_mode?: 'full' | 'script_only'
  }) {
    return this.client.post('/api/v1/audiobook/projects', payload)
  }

  getAudiobookChapterScript(audiobookProjectId: number, chapterId: number) {
    return this.client.get(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/script`
    )
  }

  updateAudiobookChapterScript(audiobookProjectId: number, chapterId: number, payload: any) {
    return this.client.put(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/script`,
      payload
    )
  }

  generateAudioFromScripts(audiobookProjectId: number, payload: any) {
    return this.client.post(
      `/api/v1/audiobook/projects/${audiobookProjectId}/generate-audio-from-scripts`,
      payload
    )
  }

  // 章节逻辑检查API
  checkChapterLogic(chapterId: number, projectId: number) {
    return this.client.post('/api/v1/ai/check-chapter-logic', {
      chapter_id: chapterId,
      project_id: projectId,
    })
  }

  // 通用API方法
  get(url: string, config?: any) {
    return this.client.get(url, config)
  }

  post(url: string, data?: any, config?: any) {
    return this.client.post(url, data, config)
  }

  put(url: string, data?: any, config?: any) {
    return this.client.put(url, data, config)
  }

  delete(url: string, config?: any) {
    return this.client.delete(url, config)
  }

  // AI生成任务API（异步）
  executeStageAsync(projectId: number, stage: string, requirement?: string) {
    return this.client.post(`/api/v1/workflow/execute-stage-async`, {
      project_id: projectId,
      stage: stage,
      requirement: requirement,
    }, {
      timeout: 5000 // 提交任务快速返回
    })
  }

  getTaskStatus(taskId: string) {
    return this.client.get(`/api/v1/workflow/task/${taskId}`, {
      timeout: 5000
    })
  }

  // 织梦映心流程（短剧生成）
  runDreamweaver(projectId: number, chapterIds: number[], options?: DreamweaverRunOptions) {
    return this.client.post('/api/v1/dreamweaver/run', {
      project_id: projectId,
      chapter_ids: chapterIds,
      schema_version: DREAMWEAVER_SCHEMA_VERSION,
      ...(options?.quality_mode ? { quality_mode: options.quality_mode } : {}),
      ...(typeof options?.qc_allow_fail === 'boolean' ? { qc_allow_fail: options.qc_allow_fail } : {}),
      ...(typeof options?.smart_tuning === 'boolean' ? { smart_tuning: options.smart_tuning } : {}),
      ...(options?.ab_variant ? { ab_variant: options.ab_variant } : {}),
      ...(typeof options?.video_require_confirmation === 'boolean'
        ? { video_require_confirmation: options.video_require_confirmation }
        : {}),
      ...(typeof options?.prompt_review_required === 'boolean'
        ? { prompt_review_required: options.prompt_review_required }
        : {}),
      ...(options?.style_preset ? { style_preset: options.style_preset } : {}),
      ...(options?.image_ratio ? { image_ratio: options.image_ratio } : {}),
      ...(options?.image_resolution ? { image_resolution: options.image_resolution } : {}),
    })
  }

  runDreamweaverAsync(projectId: number, chapterIds: number[], options?: DreamweaverRunOptions) {
    return this.client.post('/api/v1/dreamweaver/run-async', {
      project_id: projectId,
      chapter_ids: chapterIds,
      schema_version: DREAMWEAVER_SCHEMA_VERSION,
      ...(options?.quality_mode ? { quality_mode: options.quality_mode } : {}),
      ...(typeof options?.qc_allow_fail === 'boolean' ? { qc_allow_fail: options.qc_allow_fail } : {}),
      ...(typeof options?.smart_tuning === 'boolean' ? { smart_tuning: options.smart_tuning } : {}),
      ...(options?.ab_variant ? { ab_variant: options.ab_variant } : {}),
      ...(typeof options?.video_require_confirmation === 'boolean'
        ? { video_require_confirmation: options.video_require_confirmation }
        : {}),
      ...(typeof options?.prompt_review_required === 'boolean'
        ? { prompt_review_required: options.prompt_review_required }
        : {}),
      ...(options?.style_preset ? { style_preset: options.style_preset } : {}),
      ...(options?.image_ratio ? { image_ratio: options.image_ratio } : {}),
      ...(options?.image_resolution ? { image_resolution: options.image_resolution } : {}),
    })
  }

  getDreamweaverTask(taskId: string) {
    return this.client.get(`/api/v1/dreamweaver/task/${taskId}`, {
      timeout: 15000,
    })
  }

  getDreamweaverLibrary(projectId: number, options?: { run_id?: string }) {
    return this.client.get(`/api/v1/dreamweaver/library/${projectId}`, {
      params: options?.run_id ? { run_id: options.run_id } : undefined,
      timeout: 15000,
    })
  }

  getDreamweaverProjectLockedConfig(projectId: number) {
    return this.client.get<DreamweaverProjectLockedGenerationConfig>(`/api/v1/dreamweaver/projects/${projectId}/locked-config`, {
      timeout: 15000,
    })
  }

  approveDreamweaverLibrary(projectId: number, payload: DreamweaverLibraryApproveRequest) {
    return this.client.post(`/api/v1/dreamweaver/library/${projectId}/approve`, payload, {
      timeout: 15000,
    })
  }

  regenerateDreamweaverLibraryAsset(projectId: number, payload: DreamweaverLibraryRegenerateRequest) {
    return this.client.post(`/api/v1/dreamweaver/library/${projectId}/regenerate`, payload, {
      timeout: 120000,
    })
  }

  suggestDreamweaverLibraryPrompt(projectId: number, payload: DreamweaverLibraryPromptSuggestRequest) {
    return this.client.post<DreamweaverLibraryPromptSuggestResponse>(`/api/v1/dreamweaver/library/${projectId}/prompt-suggest`, payload, {
      timeout: 60000,
    })
  }

  getDreamweaverLibraryAssetFile(assetId: number) {
    return this.client.get(`/api/v1/dreamweaver/library/assets/${assetId}/file`, {
      responseType: 'blob',
      timeout: 30000,
      params: { _ts: Date.now() },
      headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    })
  }

  uploadDreamweaverLibraryAssetFile(assetId: number, file: File) {
    const form = new FormData()
    form.append('file', file)
    return this.client.post(`/api/v1/dreamweaver/library/assets/${assetId}/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  }

  uploadDreamweaverRunShotAssetFile(runId: string, shotId: string, role: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    return this.client.post(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/shots/${encodeURIComponent(shotId)}/assets/${encodeURIComponent(role)}/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  }

  updateDreamweaverRunShotFramePrompt(runId: string, shotId: string, frame: 'head' | 'tail', prompt: string) {
    return this.client.post(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/shots/${encodeURIComponent(shotId)}/frames/${encodeURIComponent(frame)}/prompt`, { prompt }, {
      timeout: 15000,
    })
  }

  updateDreamweaverRunShotVideoPrompt(runId: string, shotId: string, prompt?: string | null) {
    const payload: DreamweaverShotVideoPromptUpdateRequest = { prompt: prompt ?? '' }
    return this.client.post(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/shots/${encodeURIComponent(shotId)}/video-prompt`, payload, {
      timeout: 15000,
    })
  }

  resumeDreamweaverAsync(runId: string) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/resume-async`, null, {
      timeout: 15000,
    })
  }

  restartDreamweaverAsync(runId: string, payload: DreamweaverRestartRequest) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/restart-async`, payload, {
      timeout: 15000,
    })
  }

  confirmDreamweaverVideoJobAsync(runId: string, shotId: string) {
    return this.client.post<DreamweaverVideoJobConfirmAsyncResponse>(
      `/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/video-jobs/${encodeURIComponent(shotId)}/confirm-async`,
      null,
      { timeout: 15000 },
    )
  }

  rebuildDreamweaverVideoJobs(runId: string) {
    return this.client.post<DreamweaverVideoJobsRebuildResponse>(
      `/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/video-jobs/rebuild`,
      null,
      { timeout: 15000 },
    )
  }

  getDreamweaverRunScript(runId: string) {
    return this.client.get(`/api/v1/dreamweaver/runs/${runId}/script`, {
      timeout: 15000,
    })
  }

  updateDreamweaverRunScript(runId: string, payload: DreamweaverScriptUpdateRequest) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/script`, payload, {
      timeout: 15000,
    })
  }

  approveDreamweaverRunScript(runId: string, payload: DreamweaverScriptApproveRequest) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/script/approve`, payload, {
      timeout: 15000,
    })
  }

  approveDreamweaverPromptReview(runId: string, payload: DreamweaverPromptReviewApproveRequest) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/prompt-review/approve`, payload, {
      timeout: 15000,
    })
  }

  getDreamweaverRun(runId: string) {
    return this.client.get(`/api/v1/dreamweaver/runs/${runId}`, {
      timeout: 15000,
    })
  }

  getDreamweaverRunEvents(runId: string, params?: { after_id?: number; limit?: number }) {
    return this.client.get(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/events`, {
      params,
      timeout: 15000,
    })
  }

  getDreamweaverMergedVideoFile(runId: string) {
    return this.client.get(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/merged-video/file`, {
      responseType: 'blob',
      timeout: 60000,
    })
  }

  getDreamweaverRunAssetFile(runId: string, uri: string) {
    return this.client.get(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/assets/file`, {
      params: { uri },
      responseType: 'blob',
      timeout: 60000,
    })
  }

  listDreamweaverRuns(projectId: number, limit: number = 50) {
    return this.client.get(`/api/v1/dreamweaver/projects/${projectId}/runs`, {
      params: { limit },
      timeout: 15000,
    })
  }

  deleteDreamweaverProjectGenerated(projectId: number) {
    return this.client.delete<DreamweaverProjectGeneratedDeleteResponse>(`/api/v1/dreamweaver/projects/${projectId}/generated`, {
      timeout: 120000,
    })
  }

  deleteDreamweaverRun(runId: string, deleteFiles: boolean = true) {
    return this.client.delete(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}`, {
      params: { delete_files: deleteFiles },
      timeout: 15000,
    })
  }

  // 🌟 史诗框架状态检测API
  getEpicFrameworkState(projectId: number) {
    return this.client.get(`/api/v1/workflow/epic-framework-state/${projectId}`)
  }
}

export const apiClient = new ApiClient()

