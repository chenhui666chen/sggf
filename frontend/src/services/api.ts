import axios, { AxiosInstance, AxiosError } from 'axios'

// 在开发环境中直接连接到后端，不使用Vite代理
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

class ApiClient {
  public client: AxiosInstance

  constructor() {
    // 使用环境变量或默认值
    const baseURL = API_URL

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
        console.log('🔑 添加Authorization头:', `Bearer ${token.substring(0, 10)}...`)
      } else {
        console.warn('⚠️ Token不存在，未添加Authorization头')
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

  deleteChapter(chapterId: number) {
    return this.client.delete(`/api/v1/chapters/${chapterId}`)
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
}

export const apiClient = new ApiClient()

