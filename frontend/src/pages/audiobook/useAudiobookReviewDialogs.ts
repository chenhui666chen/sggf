import { useCallback, useState } from 'react'

import type { SetSnackbar } from './hookTypes'
import type {
  ScriptReviewDialogData,
  ScriptSegment,
  StageConfig,
  StageInfo,
  TaskStatus,
} from './types'
import { normalizePositiveId } from './editorSessionUtils'
import { normalizeScriptReview } from './utils'

interface UseAudiobookReviewDialogsParams {
  activeTaskStatus?: TaskStatus | null
  setSnackbar: SetSnackbar
}

export const useAudiobookReviewDialogs = ({
  activeTaskStatus,
  setSnackbar,
}: UseAudiobookReviewDialogsParams) => {
  const [scriptReviewDialogOpen, setScriptReviewDialogOpen] = useState(false)
  const [scriptReviewData, setScriptReviewData] = useState<ScriptReviewDialogData | null>(null)
  const [scriptReviewSelectedIssueIndex, setScriptReviewSelectedIssueIndex] = useState<number | null>(null)
  const [scriptReviewSelectedSegmentIndex, setScriptReviewSelectedSegmentIndex] = useState<number | null>(null)
  const [stageMetricsDialogOpen, setStageMetricsDialogOpen] = useState(false)
  const [stageMetricsData, setStageMetricsData] = useState<{
    stage: StageConfig
    info: StageInfo
  } | null>(null)

  const handleOpenScriptReviewDialog = useCallback(() => {
    const taskStatus = activeTaskStatus
    if (!taskStatus) {
      setSnackbar({ open: true, message: '暂未获取到任务状态', severity: 'error' })
      return
    }

    const stage = taskStatus.stages.quality_review
    if (!stage || !stage.metrics) {
      setSnackbar({ open: true, message: '暂未获取到剧本评审结果', severity: 'error' })
      return
    }

    const metrics = stage.metrics
    const report = normalizeScriptReview({
      overall_score: metrics.overall_score,
      overall_grade: metrics.overall_grade,
      issues_count: metrics.issues_count,
      script_quality: metrics.script_quality,
      audio_balance: metrics.audio_balance,
      pacing: metrics.pacing,
      revision_suggestions: metrics.revision_suggestions,
      issues: metrics.issues,
    })
    if (!report) {
      setSnackbar({ open: true, message: '暂未获取到完整的评审详情', severity: 'error' })
      return
    }

    const segments = Array.isArray(metrics.sample_segments)
      ? (metrics.sample_segments as ScriptSegment[])
      : []
    setScriptReviewData({
      report,
      segments,
      chapterId: normalizePositiveId(taskStatus.chapter_id),
    })
    setScriptReviewSelectedIssueIndex(null)
    setScriptReviewSelectedSegmentIndex(null)
    setScriptReviewDialogOpen(true)
  }, [activeTaskStatus, setSnackbar])

  const handleCloseScriptReviewDialog = useCallback(() => {
    setScriptReviewDialogOpen(false)
    setScriptReviewData(null)
    setScriptReviewSelectedIssueIndex(null)
    setScriptReviewSelectedSegmentIndex(null)
  }, [])

  const handleOpenStageMetricsDialog = useCallback((stage: StageConfig, stageInfo: StageInfo) => {
    const metrics = stageInfo.metrics
    if (!metrics || Object.keys(metrics).length === 0) {
      setSnackbar({ open: true, message: '该阶段暂无可查看的结果数据', severity: 'info' })
      return
    }
    setStageMetricsData({ stage, info: stageInfo })
    setStageMetricsDialogOpen(true)
  }, [setSnackbar])

  const handleCloseStageMetricsDialog = useCallback(() => {
    setStageMetricsDialogOpen(false)
    setStageMetricsData(null)
  }, [])

  return {
    scriptReviewDialogOpen,
    setScriptReviewDialogOpen,
    scriptReviewData,
    setScriptReviewData,
    scriptReviewSelectedIssueIndex,
    setScriptReviewSelectedIssueIndex,
    scriptReviewSelectedSegmentIndex,
    setScriptReviewSelectedSegmentIndex,
    stageMetricsDialogOpen,
    setStageMetricsDialogOpen,
    stageMetricsData,
    setStageMetricsData,
    handleOpenScriptReviewDialog,
    handleCloseScriptReviewDialog,
    handleOpenStageMetricsDialog,
    handleCloseStageMetricsDialog,
  }
}
