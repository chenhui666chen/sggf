/**
 * 统计服务 - 获取工作流阶段耗时统计
 */
import { apiClient } from './api'
import type { StageDurations } from '@/utils/progressEstimator'

export interface StageStats {
  avg: number
  min: number
  max: number
  count: number
}

export interface DetailedStageDurations {
  [stage: string]: StageStats
}

class StatisticsService {
  /**
   * 获取工作流各阶段的平均耗时
   */
  async getStageDurations(projectId?: number): Promise<StageDurations> {
    try {
      const params = projectId ? { project_id: projectId } : {}
      const response = await apiClient.client.get<StageDurations>(
        '/api/v1/statistics/workflow/stage-durations',
        { params }
      )
      return response.data
    } catch (error) {
      console.error('获取阶段耗时失败:', error)
      // 返回默认值
      return {
        concept: 120,
        structure: 90,
        content: 180,
        review: 60,
        iteration: 75
      }
    }
  }

  /**
   * 获取工作流各阶段的详细统计信息
   */
  async getDetailedStageDurations(projectId?: number): Promise<DetailedStageDurations> {
    try {
      const params = projectId ? { project_id: projectId } : {}
      const response = await apiClient.client.get<DetailedStageDurations>(
        '/api/v1/statistics/workflow/stage-durations/detailed',
        { params }
      )
      return response.data
    } catch (error) {
      console.error('获取详细阶段统计失败:', error)
      return {}
    }
  }
}

export const statisticsService = new StatisticsService()

