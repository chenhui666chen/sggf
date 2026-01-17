import { useState } from 'react'
import {
  Box,
  Button,
  Card,
  CardContent,
  Typography,
  CircularProgress,
  Alert,
  List,
  ListItem,
  ListItemText,
  Chip,
  Divider,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  IconButton,
  Tooltip,
} from '@mui/material'
import WarningIcon from '@mui/icons-material/Warning'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import RefreshIcon from '@mui/icons-material/Refresh'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import { apiClient, extractApiErrorMessage } from '@/services/api'

interface DuplicateNameConflict {
  conflict_type: 'duplicate_name'
  name: string
  items: Array<{
    id: number
    collection: string
    content: string
  }>
  severity: 'high' | 'medium' | 'low'
}

interface AbilityMismatchConflict {
  conflict_type: 'ability_mismatch'
  character: string
  technique: string
  character_realm: string
  required_realm: string
  severity: 'high' | 'medium' | 'low'
}

interface ConflictDetectorProps {
  projectId: number
  onSelectItem?: (itemId: number) => void
  title?: string
}

export default function ConflictDetector(props: ConflictDetectorProps) {
  const { projectId, onSelectItem, title = '冲突检测' } = props

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [duplicateNames, setDuplicateNames] = useState<DuplicateNameConflict[]>([])
  const [abilityMismatches, setAbilityMismatches] = useState<AbilityMismatchConflict[]>([])
  const [totalConflicts, setTotalConflicts] = useState(0)
  const [hasDetected, setHasDetected] = useState(false)

  const handleDetect = async () => {
    setLoading(true)
    setError(null)
    setHasDetected(false)

    try {
      const response = await apiClient.detectConflicts(projectId)
      const data = response.data

      setDuplicateNames(data.duplicate_names || [])
      setAbilityMismatches(data.ability_mismatches || [])
      setTotalConflicts(data.total_conflicts || 0)
      setHasDetected(true)
    } catch (err: any) {
      console.error('冲突检测失败', err)
      setError(await extractApiErrorMessage(err, '检测失败'))
    } finally {
      setLoading(false)
    }
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'high':
        return 'error'
      case 'medium':
        return 'warning'
      case 'low':
        return 'info'
      default:
        return 'default'
    }
  }

  const getSeverityLabel = (severity: string) => {
    switch (severity) {
      case 'high':
        return '严重'
      case 'medium':
        return '中等'
      case 'low':
        return '轻微'
      default:
        return '未知'
    }
  }

  return (
    <Card elevation={2}>
      <CardContent>
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
          <Box display="flex" alignItems="center" gap={1}>
            <WarningIcon color={totalConflicts > 0 ? 'warning' : 'action'} />
            <Typography variant="h6" fontWeight={600}>
              {title}
            </Typography>
            {hasDetected && (
              <Chip
                label={totalConflicts > 0 ? `发现${totalConflicts}个冲突` : '无冲突'}
                size="small"
                color={totalConflicts > 0 ? 'warning' : 'success'}
              />
            )}
          </Box>
          <Tooltip title="刷新检测">
            <IconButton size="small" onClick={handleDetect} disabled={loading}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>

        {!hasDetected && (
          <Box textAlign="center" py={3}>
            <Typography variant="body2" color="text.secondary" mb={2}>
              点击下方按钮开始检测设定冲突
            </Typography>
            <Button
              variant="contained"
              color="primary"
              onClick={handleDetect}
              disabled={loading}
              startIcon={loading ? <CircularProgress size={16} /> : <WarningIcon />}
            >
              {loading ? '检测中...' : '开始检测'}
            </Button>
          </Box>
        )}

        {loading && hasDetected && (
          <Box display="flex" justifyContent="center" py={3}>
            <CircularProgress size={24} />
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {hasDetected && !loading && totalConflicts === 0 && (
          <Alert severity="success" icon={<CheckCircleIcon />}>
            <Typography variant="body2">
              ✅ 未发现设定冲突，世界观设定一致性良好！
            </Typography>
          </Alert>
        )}

        {hasDetected && !loading && totalConflicts > 0 && (
          <Box>
            {/* 同名冲突 */}
            {duplicateNames.length > 0 && (
              <Box mb={2}>
                <Typography variant="subtitle2" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <ErrorOutlineIcon fontSize="small" color="error" />
                  同名不同定义 ({duplicateNames.length})
                </Typography>
                <List dense>
                  {duplicateNames.map((conflict, index) => (
                    <Box key={index}>
                      <Accordion>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Box display="flex" alignItems="center" gap={1} width="100%">
                            <Typography variant="body2" fontWeight={500}>
                              {conflict.name}
                            </Typography>
                            <Chip
                              label={getSeverityLabel(conflict.severity)}
                              size="small"
                              color={getSeverityColor(conflict.severity)}
                              sx={{ height: 20 }}
                            />
                            <Typography variant="caption" color="text.secondary" ml="auto">
                              {conflict.items.length} 个定义
                            </Typography>
                          </Box>
                        </AccordionSummary>
                        <AccordionDetails>
                          <List dense>
                            {conflict.items.map((item, itemIndex) => (
                              <Box key={item.id}>
                                <ListItem
                                  sx={{
                                    cursor: onSelectItem ? 'pointer' : 'default',
                                    '&:hover': onSelectItem ? { bgcolor: 'action.hover' } : {},
                                  }}
                                  onClick={() => onSelectItem && onSelectItem(item.id)}
                                >
                                  <ListItemText
                                    primary={
                                      <Box display="flex" alignItems="center" gap={1}>
                                        <Chip label={item.collection} size="small" variant="outlined" sx={{ height: 20 }} />
                                        <Typography variant="caption">ID: {item.id}</Typography>
                                      </Box>
                                    }
                                    secondary={
                                      <Typography variant="caption" color="text.secondary">
                                        {item.content}
                                      </Typography>
                                    }
                                  />
                                </ListItem>
                                {itemIndex < conflict.items.length - 1 && <Divider />}
                              </Box>
                            ))}
                          </List>
                        </AccordionDetails>
                      </Accordion>
                      {index < duplicateNames.length - 1 && <Box mb={1} />}
                    </Box>
                  ))}
                </List>
              </Box>
            )}

            {/* 能力不匹配 */}
            {abilityMismatches.length > 0 && (
              <Box>
                <Typography variant="subtitle2" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <ErrorOutlineIcon fontSize="small" color="warning" />
                  能力与境界不符 ({abilityMismatches.length})
                </Typography>
                <List dense>
                  {abilityMismatches.map((conflict, index) => (
                    <Box key={index}>
                      <ListItem
                        sx={{
                          py: 1.5,
                          bgcolor: 'warning.light',
                          borderRadius: 1,
                          mb: 1,
                        }}
                      >
                        <ListItemText
                          primary={
                            <Box display="flex" alignItems="center" gap={1} mb={0.5}>
                              <Typography variant="body2" fontWeight={500}>
                                {conflict.character} 使用 {conflict.technique}
                              </Typography>
                              <Chip
                                label={getSeverityLabel(conflict.severity)}
                                size="small"
                                color={getSeverityColor(conflict.severity)}
                                sx={{ height: 20 }}
                              />
                            </Box>
                          }
                          secondary={
                            <Box>
                              <Typography variant="caption" display="block">
                                当前境界: {conflict.character_realm || '未设置'}
                              </Typography>
                              <Typography variant="caption" display="block" color="error.main">
                                要求境界: {conflict.required_realm}
                              </Typography>
                            </Box>
                          }
                        />
                      </ListItem>
                    </Box>
                  ))}
                </List>
              </Box>
            )}
          </Box>
        )}
      </CardContent>
    </Card>
  )
}
