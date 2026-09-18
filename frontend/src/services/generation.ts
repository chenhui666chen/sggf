/**
 * 生成任务服务 - 处理AI生成内容的提交和轮询
 */

import { apiClient } from './api'

export interface GenerationTask {
  task_id: string
  task_type: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: string
  error?: string
  created_at: string
  completed_at?: string
  stage?: string
  progress?: number
}

export interface WorkflowStages {
  stage_one: 'pending' | 'running' | 'completed' | 'failed'
  stage_two: 'pending' | 'running' | 'completed' | 'failed'
  stage_three: 'pending' | 'running' | 'completed' | 'failed'
  stage_four: 'pending' | 'running' | 'completed' | 'failed'
  stage_five: 'pending' | 'running' | 'completed' | 'failed'
}

export interface GenerationParams {
  task_type: 'concept' | 'world' | 'character' | 'plot' | 'chapter'
  project_id: number
  params: Record<string, any>
}

class GenerationService {
  private pollIntervals: Map<string, NodeJS.Timeout> = new Map()
  private callbacks: Map<string, (task: GenerationTask) => void> = new Map()

  /**
   * 提交生成任务
   */
  async submitTask(
    taskType: string,
    projectId: number,
    params: Record<string, any>
  ): Promise<{ task_id: string }> {
    const response = await apiClient.client.post('/api/v1/generate', {
      task_type: taskType,
      project_id: projectId,
      params,
    })
    return response.data
  }

  /**
   * 获取任务状态
   */
  async getTaskStatus(taskId: string): Promise<GenerationTask> {
    const response = await apiClient.client.get(`/api/v1/generate/${taskId}`)
    return response.data
  }

  /**
   * 开始轮询任务状态
   */
  startPolling(
    taskId: string,
    callback: (task: GenerationTask) => void,
    interval: number = 2000
  ): void {
    this.callbacks.set(taskId, callback)

    const pollFn = async () => {
      try {
        const task = await this.getTaskStatus(taskId)
        callback(task)

        // 如果任务完成或失败，停止轮询
        if (task.status === 'completed' || task.status === 'failed') {
          this.stopPolling(taskId)
        }
      } catch {
        // 轮询任务状态失败
      }
    }

    // 立即执行一次
    pollFn()

    // 设置定时轮询
    const intervalId = setInterval(pollFn, interval)
    this.pollIntervals.set(taskId, intervalId)
  }

  /**
   * 停止轮询任务状态
   */
  stopPolling(taskId: string): void {
    const intervalId = this.pollIntervals.get(taskId)
    if (intervalId) {
      clearInterval(intervalId)
      this.pollIntervals.delete(taskId)
    }
    this.callbacks.delete(taskId)
  }

  /**
   * 停止所有轮询
   */
  stopAllPolling(): void {
    this.pollIntervals.forEach((intervalId) => {
      clearInterval(intervalId)
    })
    this.pollIntervals.clear()
    this.callbacks.clear()
  }

  /**
   * 生成项目概念
   */
  async generateConcept(
    projectId: number,
    title: string,
    genre: string,
    description: string,
    onUpdate: (task: GenerationTask) => void
  ): Promise<string> {
    const { task_id } = await this.submitTask('concept', projectId, {
      title,
      genre,
      description,
    })

    return new Promise((resolve, reject) => {
      this.startPolling(task_id, (task) => {
        onUpdate(task)
        if (task.status === 'completed') {
          resolve(task.result || '')
        } else if (task.status === 'failed') {
          reject(new Error(task.error || 'Generation failed'))
        }
      })
    })
  }

  /**
   * 生成世界观
   */
  async generateWorld(
    projectId: number,
    description: string,
    onUpdate: (task: GenerationTask) => void
  ): Promise<string> {
    const { task_id } = await this.submitTask('world', projectId, {
      description,
    })

    return new Promise((resolve, reject) => {
      this.startPolling(task_id, (task) => {
        onUpdate(task)
        if (task.status === 'completed') {
          resolve(task.result || '')
        } else if (task.status === 'failed') {
          reject(new Error(task.error || 'Generation failed'))
        }
      })
    })
  }

  /**
   * 生成人物
   */
  async generateCharacter(
    projectId: number,
    requirements: string,
    onUpdate: (task: GenerationTask) => void
  ): Promise<string> {
    const { task_id } = await this.submitTask('character', projectId, {
      requirements,
    })

    return new Promise((resolve, reject) => {
      this.startPolling(task_id, (task) => {
        onUpdate(task)
        if (task.status === 'completed') {
          resolve(task.result || '')
        } else if (task.status === 'failed') {
          reject(new Error(task.error || 'Generation failed'))
        }
      })
    })
  }

  /**
   * 生成情节
   */
  async generatePlot(
    projectId: number,
    requirements: string,
    onUpdate: (task: GenerationTask) => void
  ): Promise<string> {
    const { task_id } = await this.submitTask('plot', projectId, {
      requirements,
    })

    return new Promise((resolve, reject) => {
      this.startPolling(task_id, (task) => {
        onUpdate(task)
        if (task.status === 'completed') {
          resolve(task.result || '')
        } else if (task.status === 'failed') {
          reject(new Error(task.error || 'Generation failed'))
        }
      })
    })
  }

  /**
   * 生成章节
   */
  async generateChapter(
    projectId: number,
    chapterNumber: number,
    requirements: string,
    onUpdate: (task: GenerationTask) => void
  ): Promise<string> {
    const { task_id } = await this.submitTask('chapter', projectId, {
      chapter_number: chapterNumber,
      requirements,
    })

    return new Promise((resolve, reject) => {
      this.startPolling(task_id, (task) => {
        onUpdate(task)
        if (task.status === 'completed') {
          resolve(task.result || '')
        } else if (task.status === 'failed') {
          reject(new Error(task.error || 'Generation failed'))
        }
      })
    })
  }

  /**
   * 获取项目的完整信息（包括所有五阶段的输出）
   */
  async getProjectDetails(projectId: number): Promise<any> {
    try {
      const response = await apiClient.getProject(projectId)
      return response.data
    } catch (error) {
      throw error
    }
  }

  /**
   * 保存生成历史
   */
  async saveGenerationHistory(
    projectId: number,
    chapterId: number | undefined,
    taskType: string,
    taskId: string,
    prompt: string,
    result: string,
    status: string = 'completed',
    qualityScore?: number
  ): Promise<any> {
    try {
      const response = await apiClient.client.post('/api/v1/generation-history', {
        project_id: projectId,
        chapter_id: chapterId,
        task_type: taskType,
        task_id: taskId,
        prompt,
        result,
        status,
        quality_score: qualityScore,
      })
      return response.data
    } catch (error) {
      throw error
    }
  }

  /**
   * 获取生成历史
   */
  async getGenerationHistory(
    resourceType: 'project' | 'chapter',
    resourceId: number
  ): Promise<any> {
    try {
      const response = await apiClient.client.get(
        `/api/v1/generation-history/${resourceType}/${resourceId}`
      )
      return response.data
    } catch (error) {
      throw error
    }
  }
}

export const generationService = new GenerationService()

