import { useState } from 'react'

import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import CircularProgress from '@mui/material/CircularProgress'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'

import { apiClient, extractApiErrorMessage } from '../services/api'

interface ModelCandidate {
  model_id: string
  name: string
  provider: string
  score: number
  modality: string
  quality_score: number
  avg_latency: number
  cost: number
  recommended_scenarios: string[]
  tags: string[]
}

const SmartDispatchInput = () => {
  const [userInput, setUserInput] = useState('')
  const [strategy, setStrategy] = useState('balanced')
  const [dispatching, setDispatching] = useState(false)
  const [dispatchResult, setDispatchResult] = useState<{
    success: boolean
    intent?: Record<string, unknown>
    routing?: Record<string, unknown>
    execution?: Record<string, unknown>
    error?: string
  } | null>(null)
  const [dispatchError, setDispatchError] = useState<string | null>(null)

  const [recommending, setRecommending] = useState(false)
  const [recommendResult, setRecommendResult] = useState<{
    candidates: ModelCandidate[]
    recommended?: ModelCandidate
    reasons: string[]
  } | null>(null)
  const [recommendError, setRecommendError] = useState<string | null>(null)

  const [showDetail, setShowDetail] = useState(false)

  const handleDispatch = async () => {
    if (!userInput.trim()) return
    setDispatching(true)
    setDispatchError(null)
    setDispatchResult(null)
    try {
      const res = await apiClient.smartDispatch({
        user_input: userInput.trim(),
        strategy,
        dry_run: true,
      })
      setDispatchResult(res.data)
    } catch (err: unknown) {
      setDispatchError(await extractApiErrorMessage(err, '调度失败'))
    } finally {
      setDispatching(false)
    }
  }

  const handleRecommend = async () => {
    if (!userInput.trim()) return
    setRecommending(true)
    setRecommendError(null)
    setRecommendResult(null)
    try {
      const res = await apiClient.recommendModels({
        user_input: userInput.trim(),
        strategy,
      })
      setRecommendResult({
        candidates: res.data.candidates,
        recommended: res.data.recommended,
        reasons: res.data.reasons,
      })
    } catch (err: unknown) {
      setRecommendError(await extractApiErrorMessage(err, '模型推荐失败'))
    } finally {
      setRecommending(false)
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <AutoAwesomeIcon color="primary" fontSize="small" />
        <Typography variant="subtitle2">智能调度助手</Typography>
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
        用自然语言描述你的需求，系统将自动解析意图并推荐最佳模型或执行调度。
      </Typography>

      <TextField
        size="small"
        fullWidth
        multiline
        minRows={2}
        maxRows={4}
        placeholder="例如：帮我生成一段悬疑风格的背景音乐，时长约2分钟"
        value={userInput}
        onChange={(e) => setUserInput(e.target.value)}
        sx={{ mb: 1.5 }}
      />

      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 1.5 }}>
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel>调度策略</InputLabel>
          <Select
            label="调度策略"
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
          >
            <MenuItem value="balanced">均衡</MenuItem>
            <MenuItem value="quality">质量优先</MenuItem>
            <MenuItem value="cost">成本优先</MenuItem>
            <MenuItem value="speed">速度优先</MenuItem>
          </Select>
        </FormControl>
        <Button
          size="small"
          variant="contained"
          startIcon={dispatching ? <CircularProgress size={14} /> : <AutoAwesomeIcon />}
          onClick={handleDispatch}
          disabled={dispatching || !userInput.trim()}
        >
          {dispatching ? '调度中...' : '智能调度'}
        </Button>
        <Button
          size="small"
          variant="outlined"
          onClick={handleRecommend}
          disabled={recommending || !userInput.trim()}
        >
          {recommending ? '推荐中...' : '推荐模型'}
        </Button>
      </Box>

      {dispatchError && <Alert severity="error" sx={{ mb: 1 }}>{dispatchError}</Alert>}
      {recommendError && <Alert severity="error" sx={{ mb: 1 }}>{recommendError}</Alert>}

      {dispatchResult && (
        <Alert
          severity={dispatchResult.success ? 'success' : 'warning'}
          sx={{ mb: 1 }}
        >
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {dispatchResult.success ? '调度解析成功（预览模式）' : '调度解析失败'}
          </Typography>
          {dispatchResult.error && (
            <Typography variant="caption">{dispatchResult.error}</Typography>
          )}
          <Button
            size="small"
            variant="text"
            endIcon={showDetail ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            onClick={() => setShowDetail(!showDetail)}
            sx={{ mt: 0.5 }}
          >
            {showDetail ? '收起详情' : '查看详情'}
          </Button>
          <Collapse in={showDetail}>
            <Box sx={{ mt: 1 }}>
              {dispatchResult.intent && (
                <Typography variant="caption" component="div" color="text.secondary">
                  意图：{JSON.stringify(dispatchResult.intent, null, 2)}
                </Typography>
              )}
              {dispatchResult.routing && (
                <Typography variant="caption" component="div" color="text.secondary" sx={{ mt: 0.5 }}>
                  路由：{JSON.stringify(dispatchResult.routing, null, 2)}
                </Typography>
              )}
            </Box>
          </Collapse>
        </Alert>
      )}

      {recommendResult && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>推荐结果</Typography>
          {recommendResult.reasons.length > 0 && (
            <Box sx={{ mb: 1 }}>
              {recommendResult.reasons.map((reason, i) => (
                <Typography key={i} variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                  • {reason}
                </Typography>
              ))}
            </Box>
          )}
          {recommendResult.recommended && (
            <Paper variant="outlined" sx={{ p: 1.5, mb: 1, borderColor: 'primary.main' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                <Chip label="推荐" size="small" color="primary" sx={{ height: 20, fontSize: '0.65rem' }} />
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {recommendResult.recommended.name}
                </Typography>
              </Box>
              <Typography variant="caption" color="text.secondary">
                提供商：{recommendResult.recommended.provider} | 质量：{recommendResult.recommended.quality_score.toFixed(2)} | 延迟：{recommendResult.recommended.avg_latency.toFixed(1)}s | 费用：￥{recommendResult.recommended.cost.toFixed(4)}
              </Typography>
            </Paper>
          )}
          {recommendResult.candidates.filter(c => c !== recommendResult.recommended).length > 0 && (
            <Box>
              <Typography variant="caption" color="text.secondary">备选模型：</Typography>
              {recommendResult.candidates
                .filter(c => c !== recommendResult.recommended)
                .map((c) => (
                  <Paper key={c.model_id} variant="outlined" sx={{ p: 1, mt: 0.5 }}>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>{c.name}</Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      {c.provider} | 质量：{c.quality_score.toFixed(2)} | 延迟：{c.avg_latency.toFixed(1)}s | 费用：￥{c.cost.toFixed(4)}
                    </Typography>
                  </Paper>
                ))}
            </Box>
          )}
        </Box>
      )}
    </Paper>
  )
}

export default SmartDispatchInput
