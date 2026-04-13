/**
 * 统计服务 - 获取工作流阶段耗时统计
 */
import { apiClient } from './api'
import type { StageDurations, StageDurationRanges } from '@/utils/progressEstimator'

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
  async getStageDurations(projectId?: number, recentCount?: number): Promise<StageDurations> {
    try {
      const params: any = {}
      if (projectId) params.project_id = projectId
      if (recentCount) params.recent_count = recentCount

      const response = await apiClient.client.get<StageDurations>(
        '/api/v1/statistics/workflow/stage-durations',
        { params }
      )

      return response.data
    } catch {
      return {
        concept: 120,
        structure: 90,
        content: 180,
        review: 60,
        iteration: 75
      }
    }
  }

  async getDetailedStageDurations(projectId?: number): Promise<DetailedStageDurations> {
    try {
      const params = projectId ? { project_id: projectId } : {}
      const response = await apiClient.client.get<DetailedStageDurations>(
        '/api/v1/statistics/workflow/stage-durations/detailed',
        { params }
      )
      return response.data
    } catch {
      return {}
    }
  }

  async getStageDurationRanges(projectId?: number): Promise<StageDurationRanges | null> {
    try {
      const detailed = await this.getDetailedStageDurations(projectId)

      const ranges: any = {}
      const stages = ['concept', 'structure', 'content', 'review', 'iteration']

      for (const stage of stages) {
        if (detailed[stage]) {
          ranges[stage] = {
            min: detailed[stage].min,
            max: detailed[stage].max
          }
        }
      }

      const hasData = Object.keys(ranges).length > 0
      if (!hasData) {
        return null
      }

      return ranges as StageDurationRanges
    } catch {
      return null
    }
  }
}

export const statisticsService = new StatisticsService()
