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
  /**
   * 获取工作流各阶段的平均耗时
   * @param projectId 可选，指定项目ID
   * @param recentCount 可选，只统计最近N次任务（自适应学习）
   */
  async getStageDurations(projectId?: number, recentCount?: number): Promise<StageDurations> {
    try {
      const params: any = {}
      if (projectId) params.project_id = projectId
      if (recentCount) params.recent_count = recentCount

      const response = await apiClient.client.get<StageDurations>(
        '/api/v1/statistics/workflow/stage-durations',
        { params }
      )

      // 🆕 日志输出：显示使用的是自适应预估还是全局平均
      if (recentCount) {
        console.log(`📊 使用自适应预估（最近${recentCount}次任务）:`, response.data)
      } else {
        console.log('📊 使用全局平均耗时:', response.data)
      }

      return response.data
    } catch (error) {
      console.error('获取阶段耗时失败:', error)
      console.log('📊 使用默认耗时值')
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

  /**
   * 🆕 获取阶段耗时的置信区间
   */
  async getStageDurationRanges(projectId?: number): Promise<StageDurationRanges | null> {
    try {
      const detailed = await this.getDetailedStageDurations(projectId)

      // 转换为置信区间格式
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

      // 检查是否有足够的数据
      const hasData = Object.keys(ranges).length > 0
      if (!hasData) {
        console.log('⚠️ 没有历史数据，无法计算置信区间')
        return null
      }

      console.log('📊 阶段耗时置信区间:', ranges)
      return ranges as StageDurationRanges
    } catch (error) {
      console.error('获取置信区间失败:', error)
      return null
    }
  }
}

export const statisticsService = new StatisticsService()

