import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import FactCheckIcon from '@mui/icons-material/FactCheck'
import RefreshIcon from '@mui/icons-material/Refresh'

import {
  apiClient,
  extractApiErrorMessage,
  type PromptAudioReviewSummaryResponse,
} from '../../services/api'
import { triggerBlobDownload } from '../../utils/blobDownload'
import { audiobookButtonSx, audiobookColors, audiobookPanelSx } from './audiobookTheme'
import { extractDownloadFilename } from './utils'

interface PromptAudioReviewSummaryPanelProps {
  audiobookProjectId?: number | null
}

const formatRate = (value: number | null | undefined) => (
  typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toFixed(1)}%`
    : '未评'
)

const formatScore = (value: number | null | undefined) => (
  typeof value === 'number' && Number.isFinite(value)
    ? value.toFixed(1)
    : '未评'
)

const formatCount = (value: number | null | undefined) => (
  typeof value === 'number' && Number.isFinite(value) ? value : 0
)

const PromptAudioReviewSummaryPanel = ({
  audiobookProjectId,
}: PromptAudioReviewSummaryPanelProps) => {
  const [summary, setSummary] = useState<PromptAudioReviewSummaryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const canLoad = Boolean(audiobookProjectId)

  const loadSummary = useCallback(async () => {
    if (!audiobookProjectId) {
      return
    }

    setLoading(true)
    setError(null)
    try {
      const response = await apiClient.getPromptAudioReviewSummary(audiobookProjectId)
      setSummary(response.data)
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '加载 Prompt/Audio 验收汇总失败'))
    } finally {
      setLoading(false)
    }
  }, [audiobookProjectId])

  useEffect(() => {
    void loadSummary()
  }, [loadSummary])

  const handleExportCsv = useCallback(async () => {
    if (!audiobookProjectId) {
      return
    }

    setExporting(true)
    setError(null)
    setSuccessMessage(null)
    try {
      const response = await apiClient.downloadPromptAudioReviewSummaryCsv(audiobookProjectId)
      const filename = extractDownloadFilename(
        response.headers?.['content-disposition'],
        `prompt_audio_review_summary_${audiobookProjectId}.csv`,
      )
      triggerBlobDownload(response.data, filename)
      setSuccessMessage('Prompt/Audio 验收汇总 CSV 已开始下载')
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '导出 Prompt/Audio 验收汇总失败'))
    } finally {
      setExporting(false)
    }
  }, [audiobookProjectId])

  const coverageItems = useMemo(() => {
    const coverage = summary?.coverage
    return [
      {
        label: '质量回写章节',
        value: `${formatCount(coverage?.chapter_audio_with_quality_count)}/${formatCount(coverage?.chapter_audio_count)}`,
      },
      {
        label: '已验收模型',
        value: formatCount(coverage?.reviewed_model_count),
      },
      {
        label: '标签解析样本',
        value: formatCount(coverage?.tag_parse_reviewed_count),
      },
      {
        label: '评分样本',
        value: formatCount(coverage?.score_reviewed_count),
      },
      {
        label: 'ASR 辅助样本',
        value: formatCount(coverage?.asr_assist_count),
      },
      {
        label: 'ASR 标签残留',
        value: formatCount(coverage?.asr_tag_residue_count),
      },
    ]
  }, [summary])

  if (!canLoad) {
    return null
  }

  return (
    <Box sx={{ ...audiobookPanelSx, p: 2.5, mb: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1.5, mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <FactCheckIcon sx={{ color: audiobookColors.collect }} />
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              Prompt/Audio 验收汇总
            </Typography>
            <Typography variant="caption" color="text.secondary">
              按 TTS 模型汇总标签解析、正文污染与人工评分
            </Typography>
          </Box>
        </Box>

        <Stack direction="row" spacing={1}>
          <Tooltip title="刷新汇总">
            <span>
              <Button
                size="small"
                variant="outlined"
                startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                onClick={loadSummary}
                disabled={loading}
                sx={audiobookButtonSx.neutralOutlined}
              >
                刷新
              </Button>
            </span>
          </Tooltip>
          <Tooltip title="导出 CSV">
            <span>
              <Button
                size="small"
                variant="outlined"
                startIcon={exporting ? <CircularProgress size={16} color="inherit" /> : <DownloadIcon />}
                onClick={handleExportCsv}
                disabled={exporting || !summary}
                sx={audiobookButtonSx.collectOutlined}
              >
                导出
              </Button>
            </span>
          </Tooltip>
        </Stack>
      </Box>

      {loading && <LinearProgress sx={{ mb: 2 }} />}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {successMessage && <Alert severity="success" sx={{ mb: 2 }}>{successMessage}</Alert>}

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(6, minmax(0, 1fr))' },
          gap: 1,
          mb: 2,
        }}
      >
        {coverageItems.map((item) => (
          <Box
            key={item.label}
            sx={{
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              p: 1.25,
              backgroundColor: 'background.paper',
            }}
          >
            <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
              {item.value}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {item.label}
            </Typography>
          </Box>
        ))}
      </Box>

      {summary && summary.models.length > 0 ? (
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small" sx={{ minWidth: 920 }}>
            <TableHead>
              <TableRow>
                <TableCell>模型</TableCell>
                <TableCell align="right">章节</TableCell>
                <TableCell align="right">已验收</TableCell>
                <TableCell align="right">标签解析成功率</TableCell>
                <TableCell align="right">正文污染率</TableCell>
                <TableCell align="right">平均分</TableCell>
                <TableCell align="right">ASR 辅助</TableCell>
                <TableCell align="right">标签残留</TableCell>
                <TableCell align="right">缺失音频</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {summary.models.map((model) => (
                <TableRow key={model.model} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {model.model}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {model.model_family || 'unknown'}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">{model.chapter_audio_count}</TableCell>
                  <TableCell align="right">{model.reviewed_model_count}</TableCell>
                  <TableCell align="right">{formatRate(model.tag_parse_success_rate)}</TableCell>
                  <TableCell align="right">{formatRate(model.text_contamination_rate)}</TableCell>
                  <TableCell align="right">{formatScore(model.average_score)}</TableCell>
                  <TableCell align="right">{model.asr_assist_count}</TableCell>
                  <TableCell align="right">{model.asr_tag_residue_count}</TableCell>
                  <TableCell align="right">{model.missing_audio_count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      ) : (
        <Alert severity="info">
          暂无可汇总的 Prompt/Audio 质量回写。
        </Alert>
      )}
    </Box>
  )
}

export default PromptAudioReviewSummaryPanel
