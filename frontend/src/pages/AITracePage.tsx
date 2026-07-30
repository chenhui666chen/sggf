import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box,
  Container,
  Typography,
  Paper,
  TextField,
  Button,
  CircularProgress,
  LinearProgress,
  Chip,
  IconButton,
  Tooltip,
  Fade,
  Alert,
  Divider,
  Grid,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ContentPasteIcon from '@mui/icons-material/ContentPaste'
import SearchIcon from '@mui/icons-material/Search'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DeleteIcon from '@mui/icons-material/Delete'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import WarningIcon from '@mui/icons-material/Warning'
import ErrorIcon from '@mui/icons-material/Error'
import { apiClient } from '@/services/api'
import { AI_TRACE_GENRES, normalizeAITraceGenre } from './aiTraceGenre'

// AI分数等级配置
const getScoreLevel = (score: number) => {
  if (score <= 30) return { label: '低AI痕迹', color: '#4caf50', icon: CheckCircleIcon }
  if (score <= 60) return { label: '中等AI痕迹', color: '#ff9800', icon: WarningIcon }
  return { label: '高AI痕迹', color: '#f44336', icon: ErrorIcon }
}

export default function AITracePage() {
  const navigate = useNavigate()
  const [inputText, setInputText] = useState('')
  const [outputText, setOutputText] = useState('')
  const [detecting, setDetecting] = useState(false)
  const [reducing, setReducing] = useState(false)
  const [genre, setGenre] = useState<string>('auto')
  const [sourceType, setSourceType] = useState<'paste' | 'import'>('paste')
  const [detectResult, setDetectResult] = useState<{
    score: number
    label: string
    suggestion: string
  } | null>(null)
  const [reducedResult, setReducedResult] = useState<{
    score: number
    label: string
    modelUsed: string | null
    genreDetected: string | null
  } | null>(null)
  const [error, setError] = useState('')
  const [copySuccess, setCopySuccess] = useState(false)

  // 从 localStorage 读取导入的章节内容
  useEffect(() => {
    const importedContent = localStorage.getItem('zhiwen_import_content')
    if (importedContent) {
      try {
        const data = JSON.parse(importedContent)
        setInputText(data.content || '')
        setSourceType('import')
        setGenre(normalizeAITraceGenre(data.genre))
        localStorage.removeItem('zhiwen_import_content')
      } catch {
        // 解析导入数据失败
      }
    }
  }, [])

  // 从剪贴板粘贴
  const handlePaste = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText()
      setInputText(text)
      setError('')
      setDetectResult(null)
      setReducedResult(null)
      setOutputText('')
    } catch {
      setError('无法读取剪贴板，请手动粘贴')
    }
  }, [])

  // 清空内容
  const handleClear = useCallback(() => {
    setInputText('')
    setOutputText('')
    setDetectResult(null)
    setReducedResult(null)
    setError('')
  }, [])

  // 检测AI浓度
  const handleDetect = useCallback(async () => {
    if (!inputText.trim()) {
      setError('请先输入或粘贴要检测的文本')
      return
    }
    setDetecting(true)
    setError('')
    try {
      const response = await apiClient.client.post('/api/v1/ai-detect', { text: inputText })
      if (response.data.success) {
        setDetectResult({
          score: response.data.ai_score,
          label: response.data.label,
          suggestion: response.data.suggestion,
        })
      } else {
        setError(response.data.error || '检测失败')
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : '检测请求失败'
      setError(errorMessage)
    } finally {
      setDetecting(false)
    }
  }, [inputText])

  // 降低AI浓度（使用活跃模型）
  const handleReduce = useCallback(async () => {
    if (!inputText.trim()) {
      setError('请先输入或粘贴要处理的文本')
      return
    }
    setReducing(true)
    setError('')
    setOutputText('')
    setReducedResult(null)
    try {
      const requestData: {
        text: string
        intensity: string
        original_ai_score?: number
        genre?: string
        source?: string
      } = { text: inputText, intensity: 'medium', source: sourceType }

      // genre: 'auto' 表示不传，让后端自动检测
      if (genre !== 'auto') {
        requestData.genre = genre
      }

      if (detectResult?.score !== undefined) {
        requestData.original_ai_score = detectResult.score
      }

      const response = await apiClient.client.post(
        '/api/v1/ai-trace/reduce',
        requestData,
        { timeout: 300000 }
      )
      if (response.data.success) {
        setOutputText(response.data.reduced_text)
        setReducedResult({
          score: response.data.new_ai_score,
          label: response.data.label,
          modelUsed: response.data.model_used || null,
          genreDetected: response.data.genre_detected || null,
        })
        if (!detectResult && response.data.original_ai_score !== undefined) {
          setDetectResult({
            score: response.data.original_ai_score,
            label: 'Unknown',
            suggestion: 'Pass',
          })
        }
      } else {
        setError(response.data.error || '降低AI浓度失败')
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : '处理请求失败'
      setError(errorMessage)
    } finally {
      setReducing(false)
    }
  }, [inputText, detectResult])

  // 复制结果
  const handleCopy = useCallback(async () => {
    if (outputText) {
      await navigator.clipboard.writeText(outputText)
      setCopySuccess(true)
      setTimeout(() => setCopySuccess(false), 2000)
    }
  }, [outputText])

  const charCount = inputText.length
  const scoreLevel = detectResult ? getScoreLevel(detectResult.score) : null
  const reducedLevel = reducedResult ? getScoreLevel(reducedResult.score) : null

  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #1a237e 0%, #0d47a1 50%, #01579b 100%)' }}>
      {/* 顶部导航 */}
      <Box sx={{ py: 2, px: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
        <IconButton onClick={() => navigate('/home')} sx={{ color: 'white' }}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" sx={{ color: 'white', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 1 }}>
          <AutoFixHighIcon /> 织文无迹
        </Typography>
        <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.7)', ml: 1 }}>
          智能检测与降低AI写作痕迹
        </Typography>
      </Box>

      <Container maxWidth="xl" sx={{ pb: 4 }}>
        {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

        <Grid container spacing={3}>
          {/* 左侧：输入区域 */}
          <Grid item xs={12} md={6}>
            <Paper sx={{ p: 3, borderRadius: 3, height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column' }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6" sx={{ fontWeight: 600, color: '#1a237e' }}>
                  输入文本
                </Typography>
                <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ mr: 1 }}>
                    字数：{charCount} / 10000
                  </Typography>
                  <Tooltip title="从剪贴板粘贴">
                    <IconButton size="small" onClick={handlePaste} color="primary">
                      <ContentPasteIcon />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="清空">
                    <IconButton size="small" onClick={handleClear} color="error">
                      <DeleteIcon />
                    </IconButton>
                  </Tooltip>
                </Box>
              </Box>

              <TextField
                multiline
                fullWidth
                placeholder={'在此粘贴或输入要检测的文本内容...\n\n支持小说、文章、论文等各类文本\n建议文本长度：100-10000字'}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                sx={{ flex: 1, '& .MuiOutlinedInput-root': { height: '100%', alignItems: 'flex-start' },
                  '& .MuiInputBase-input': { height: '100% !important', overflow: 'auto !important' } }}
                InputProps={{ sx: { height: '100%', fontSize: '0.95rem', lineHeight: 1.8 } }}
              />

              <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
                <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Button variant="outlined" startIcon={detecting ? <CircularProgress size={18} /> : <SearchIcon />}
                    onClick={handleDetect} disabled={detecting || !inputText.trim()}>
                    {detecting ? '检测中...' : '检测AI浓度'}
                  </Button>

                  <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', alignItems: 'center' }}>
                    <Chip
                      label="自动"
                      size="small"
                      color={genre === 'auto' ? 'primary' : 'default'}
                      variant={genre === 'auto' ? 'filled' : 'outlined'}
                      onClick={() => setGenre('auto')}
                    />
                    {AI_TRACE_GENRES.map((option) => (
                      <Chip
                        key={option}
                        label={option}
                        size="small"
                        color={genre === option ? 'primary' : 'default'}
                        variant={genre === option ? 'filled' : 'outlined'}
                        onClick={() => setGenre(option)}
                      />
                    ))}
                  </Box>

                  <Button
                    variant="contained"
                    startIcon={reducing ? <CircularProgress size={18} color="inherit" /> : <AutoFixHighIcon />}
                    onClick={handleReduce}
                    disabled={reducing || !inputText.trim()}
                    sx={{
                      background: 'linear-gradient(45deg, #1a237e 30%, #0d47a1 90%)',
                      '&:hover': {
                        background: 'linear-gradient(45deg, #0d47a1 30%, #01579b 90%)',
                      },
                      '&.Mui-disabled': {
                        background: 'linear-gradient(45deg, #7986cb 30%, #90caf9 90%)',
                        color: 'rgba(255, 255, 255, 0.7)',
                      }
                    }}
                  >
                    {reducing ? '处理中...' : '一键降低AI浓度'}
                  </Button>
                </Box>
              </Box>

              {/* 检测结果展示 */}
              {detectResult && scoreLevel && (
                <Fade in>
                  <Box sx={{ mt: 2, p: 2, borderRadius: 2, backgroundColor: `${scoreLevel.color}15`, border: `1px solid ${scoreLevel.color}40` }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      <Box sx={{ position: 'relative', display: 'inline-flex' }}>
                        <CircularProgress variant="determinate" value={detectResult.score} size={60}
                          sx={{ color: scoreLevel.color }} />
                        <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Typography variant="body2" sx={{ fontWeight: 700, color: scoreLevel.color }}>
                            {detectResult.score}
                          </Typography>
                        </Box>
                      </Box>
                      <Box>
                        <Chip icon={<scoreLevel.icon />} label={scoreLevel.label} size="small"
                          sx={{ backgroundColor: scoreLevel.color, color: 'white', fontWeight: 600 }} />
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                          {detectResult.suggestion === 'Pass' ? '内容可直接使用' : '建议进行优化处理'}
                        </Typography>
                      </Box>
                    </Box>
                  </Box>
                </Fade>
              )}
            </Paper>
          </Grid>

          {/* 右侧：输出区域 */}
          <Grid item xs={12} md={6}>
            <Paper sx={{ p: 3, borderRadius: 3, height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column' }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6" sx={{ fontWeight: 600, color: '#2e7d32' }}>
                  优化结果
                </Typography>
                {outputText && (
                  <Tooltip title={copySuccess ? '已复制!' : '复制结果'}>
                    <IconButton size="small" onClick={handleCopy} color={copySuccess ? 'success' : 'primary'}>
                      {copySuccess ? <CheckCircleIcon /> : <ContentCopyIcon />}
                    </IconButton>
                  </Tooltip>
                )}
              </Box>

              {reducing && (
                <Box sx={{ mb: 2 }}>
                  <LinearProgress sx={{ borderRadius: 1 }} />
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1, textAlign: 'center' }}>
                    正在使用AI降痕技术处理文本，请稍候...
                  </Typography>
                </Box>
              )}

              <TextField multiline fullWidth placeholder="优化后的文本将显示在这里..." value={outputText}
                InputProps={{ readOnly: true, sx: { height: '100%', fontSize: '0.95rem', lineHeight: 1.8, backgroundColor: outputText ? '#f8fff8' : 'transparent' } }}
                sx={{ flex: 1, '& .MuiOutlinedInput-root': { height: '100%', alignItems: 'flex-start' },
                  '& .MuiInputBase-input': { height: '100% !important', overflow: 'auto !important' } }}
              />

              {/* 优化结果对比 */}
              {reducedResult && reducedLevel && detectResult && (
                <Fade in>
                  <Box sx={{ mt: 2 }}>
                    <Divider sx={{ mb: 2 }} />
                    <Box sx={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center' }}>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">处理前</Typography>
                        <Typography variant="h5" sx={{ color: getScoreLevel(detectResult.score).color, fontWeight: 700 }}>
                          {detectResult.score}分
                        </Typography>
                      </Box>
                      <Box sx={{ fontSize: 24 }}>&rarr;</Box>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">处理后</Typography>
                        <Typography variant="h5" sx={{ color: reducedLevel.color, fontWeight: 700 }}>
                          {reducedResult.score}分
                        </Typography>
                      </Box>
                      <Chip label={`降低 ${detectResult.score - reducedResult.score} 分`} color="success" sx={{ fontWeight: 600 }} />
                    </Box>
                  </Box>
                </Fade>
              )}
              {reducedResult && (
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5, textAlign: 'center' }}>
                  使用模型：{reducedResult.modelUsed || '默认路由'} | 题材：{reducedResult.genreDetected || '通用'}
                </Typography>
              )}
            </Paper>
          </Grid>
        </Grid>
      </Container>
    </Box>
  )
}
