import { useState, useCallback, useEffect, type ChangeEvent } from 'react'
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
  alpha,
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
import { useTranslation } from 'react-i18next'
import { apiClient } from '@/services/api'
import { AI_TRACE_GENRES, AI_TRACE_GENRE_LABEL_KEYS, normalizeAITraceGenre } from './aiTraceGenre'

// AI分数等级配置：tone 走语义 token（success/warning/error），随主题反相；labelKey 供显示层取翻译。
interface ScoreLevelInfo {
  label: string
  labelKey: string
  tone: 'success' | 'warning' | 'error'
  icon: typeof CheckCircleIcon
}
const getScoreLevel = (score: number): ScoreLevelInfo => {
  if (score <= 30) return { label: '低AI痕迹', labelKey: 'aiTrace.scoreLow', tone: 'success', icon: CheckCircleIcon }
  if (score <= 60) return { label: '中等AI痕迹', labelKey: 'aiTrace.scoreMedium', tone: 'warning', icon: WarningIcon }
  return { label: '高AI痕迹', labelKey: 'aiTrace.scoreHigh', tone: 'error', icon: ErrorIcon }
}

export default function AITracePage() {
  const { t } = useTranslation()
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
    text: string
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
      setError(t('aiTrace.pasteFailed'))
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

  const handleInputChange = useCallback((event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setInputText(event.target.value)
    setDetectResult(null)
    setReducedResult(null)
    setOutputText('')
    setError('')
  }, [])

  // 检测AI浓度
  const handleDetect = useCallback(async () => {
    if (!inputText.trim()) {
      setError(t('aiTrace.detectInputRequired'))
      return
    }
    setDetecting(true)
    setError('')
    const detectedText = inputText
    try {
      const response = await apiClient.client.post('/api/v1/ai-detect', { text: detectedText })
      if (response.data.success) {
        setDetectResult({
          score: response.data.ai_score,
          label: response.data.label,
          suggestion: response.data.suggestion,
          text: detectedText,
        })
      } else {
        setError(response.data.error || t('aiTrace.detectFailed'))
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : t('aiTrace.detectRequestFailed')
      setError(errorMessage)
    } finally {
      setDetecting(false)
    }
  }, [inputText])

  // 降低AI浓度（使用活跃模型）
  const handleReduce = useCallback(async () => {
    if (!inputText.trim()) {
      setError(t('aiTrace.reduceInputRequired'))
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

      if (detectResult?.score !== undefined && detectResult.text === inputText) {
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
            text: inputText,
          })
        }
      } else {
        setError(response.data.error || t('aiTrace.reduceFailed'))
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : t('aiTrace.reduceRequestFailed')
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
  const currentDetectResult = detectResult?.text === inputText ? detectResult : null
  const scoreLevel = currentDetectResult ? getScoreLevel(currentDetectResult.score) : null
  const reducedLevel = reducedResult ? getScoreLevel(reducedResult.score) : null

  return (
    <Box sx={(theme) => ({ minHeight: '100vh', background: `linear-gradient(135deg, ${theme.palette.primary.main} 0%, ${theme.palette.primary.dark} 100%)` })}>
      {/* 顶部导航 */}
      <Box sx={{ py: 2, px: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
        <IconButton onClick={() => navigate('/home')} sx={{ color: 'primary.contrastText' }}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" sx={{ color: 'primary.contrastText', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 1 }}>
          <AutoFixHighIcon /> {t('aiTrace.pageTitle')}
        </Typography>
        <Typography variant="body2" sx={(theme) => ({ color: alpha(theme.palette.primary.contrastText, 0.7), ml: 1 })}>
          {t('aiTrace.subtitle')}
        </Typography>
      </Box>

      <Container maxWidth="xl" sx={{ pb: 4 }}>
        {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

        <Grid container spacing={3}>
          {/* 左侧：输入区域 */}
          <Grid item xs={12} md={6}>
            <Paper sx={{ p: 3, borderRadius: 3, height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column' }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6" sx={{ fontWeight: 600, color: 'primary.main' }}>
                  {t('aiTrace.inputTitle')}
                </Typography>
                <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ mr: 1 }}>
                    {t('aiTrace.charCount', { count: charCount })}
                  </Typography>
                  <Tooltip title={t('aiTrace.pasteTooltip')}>
                    <IconButton size="small" onClick={handlePaste} color="primary">
                      <ContentPasteIcon />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title={t('aiTrace.clearTooltip')}>
                    <IconButton size="small" onClick={handleClear} color="error">
                      <DeleteIcon />
                    </IconButton>
                  </Tooltip>
                </Box>
              </Box>

              <TextField
                multiline
                fullWidth
                placeholder={t('aiTrace.inputPlaceholder')}
                value={inputText}
                onChange={handleInputChange}
                sx={{ flex: 1, '& .MuiOutlinedInput-root': { height: '100%', alignItems: 'flex-start' },
                  '& .MuiInputBase-input': { height: '100% !important', overflow: 'auto !important' } }}
                InputProps={{ sx: { height: '100%', fontSize: '0.95rem', lineHeight: 1.8 } }}
              />

              <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
                <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Button variant="outlined" startIcon={detecting ? <CircularProgress size={18} /> : <SearchIcon />}
                    onClick={handleDetect} disabled={detecting || !inputText.trim()}>
                    {detecting ? t('aiTrace.detecting') : t('aiTrace.detectLabel')}
                  </Button>

                  <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', alignItems: 'center' }}>
                    <Chip
                      label={t('aiTrace.autoGenre')}
                      size="small"
                      color={genre === 'auto' ? 'primary' : 'default'}
                      variant={genre === 'auto' ? 'filled' : 'outlined'}
                      onClick={() => setGenre('auto')}
                    />
                    {AI_TRACE_GENRES.map((option) => (
                      <Chip
                        key={option}
                        label={AI_TRACE_GENRE_LABEL_KEYS[option] ? t(AI_TRACE_GENRE_LABEL_KEYS[option]) : option}
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
                    sx={(theme) => ({
                      // 主操作按钮渐变走 primary token 反相，禁用态扁平化走 action token。
                      background: `linear-gradient(45deg, ${theme.palette.primary.main} 30%, ${theme.palette.primary.dark} 90%)`,
                      '&:hover': {
                        background: `linear-gradient(45deg, ${theme.palette.primary.dark} 30%, ${theme.palette.primary.dark} 90%)`,
                      },
                      '&.Mui-disabled': {
                        background: theme.palette.action.disabledBackground,
                        color: theme.palette.text.disabled,
                      }
                    })}
                  >
                    {reducing ? t('aiTrace.reducing') : t('aiTrace.reduceLabel')}
                  </Button>
                </Box>
              </Box>

              {/* 检测结果展示 */}
              {currentDetectResult && scoreLevel && (
                <Fade in>
                  <Box sx={(theme) => ({ mt: 2, p: 2, borderRadius: 2, backgroundColor: alpha(theme.palette[scoreLevel.tone].main, 0.08), border: `1px solid ${alpha(theme.palette[scoreLevel.tone].main, 0.25)}` })}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      <Box sx={{ position: 'relative', display: 'inline-flex' }}>
                        <CircularProgress variant="determinate" value={currentDetectResult.score} size={60}
                          sx={(theme) => ({ color: theme.palette[scoreLevel.tone].main })} />
                        <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Typography variant="body2" sx={(theme) => ({ fontWeight: 700, color: theme.palette[scoreLevel.tone].main })}>
                            {currentDetectResult.score}
                          </Typography>
                        </Box>
                      </Box>
                      <Box>
                        <Chip icon={<scoreLevel.icon />} label={scoreLevel.labelKey ? t(scoreLevel.labelKey) : scoreLevel.label} size="small"
                          sx={(theme) => ({ backgroundColor: theme.palette[scoreLevel.tone].main, color: theme.palette[scoreLevel.tone].contrastText, fontWeight: 600 })} />
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                          {currentDetectResult.suggestion === 'Pass' ? t('aiTrace.suggestionPass') : t('aiTrace.suggestionOptimize')}
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
                <Typography variant="h6" sx={{ fontWeight: 600, color: 'success.main' }}>
                  {t('aiTrace.outputTitle')}
                </Typography>
                {outputText && (
                  <Tooltip title={copySuccess ? t('aiTrace.copied') : t('aiTrace.copyResult')}>
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
                    {t('aiTrace.reducingHint')}
                  </Typography>
                </Box>
              )}

              <TextField multiline fullWidth placeholder={t('aiTrace.outputPlaceholder')} value={outputText}
                InputProps={{ readOnly: true, sx: { height: '100%', fontSize: '0.95rem', lineHeight: 1.8, backgroundColor: outputText ? 'success.light' : 'transparent' } }}
                sx={{ flex: 1, '& .MuiOutlinedInput-root': { height: '100%', alignItems: 'flex-start' },
                  '& .MuiInputBase-input': { height: '100% !important', overflow: 'auto !important' } }}
              />

              {/* 优化结果对比 */}
              {reducedResult && reducedLevel && currentDetectResult && (
                <Fade in>
                  <Box sx={{ mt: 2 }}>
                    <Divider sx={{ mb: 2 }} />
                    <Box sx={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center' }}>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">{t('aiTrace.beforeLabel')}</Typography>
                        <Typography variant="h5" sx={(theme) => ({ color: theme.palette[getScoreLevel(currentDetectResult.score).tone].main, fontWeight: 700 })}>
                          {t('aiTrace.scorePoint', { score: currentDetectResult.score })}
                        </Typography>
                      </Box>
                      <Box sx={{ fontSize: 24 }}>&rarr;</Box>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">{t('aiTrace.afterLabel')}</Typography>
                        <Typography variant="h5" sx={(theme) => ({ color: theme.palette[reducedLevel.tone].main, fontWeight: 700 })}>
                          {t('aiTrace.scorePoint', { score: reducedResult.score })}
                        </Typography>
                      </Box>
                      <Chip label={t('aiTrace.scoreReduced', { delta: currentDetectResult.score - reducedResult.score })} color="success" sx={{ fontWeight: 600 }} />
                    </Box>
                  </Box>
                </Fade>
              )}
              {reducedResult && (
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5, textAlign: 'center' }}>
                  {t('aiTrace.usageMeta', {
                    model: reducedResult.modelUsed || t('aiTrace.defaultRoute'),
                    genre: reducedResult.genreDetected || t('aiTrace.genericGenre'),
                  })}
                </Typography>
              )}
            </Paper>
          </Grid>
        </Grid>
      </Container>
    </Box>
  )
}
