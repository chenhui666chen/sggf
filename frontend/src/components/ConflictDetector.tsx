import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
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

interface RelationConflict {
  conflict_type: 'relation_conflict'
  source: string
  target: string
  forward_relation: string
  reverse_relation: string
  description: string
  severity: 'high' | 'medium' | 'low'
}

interface ConflictDetectorProps {
  projectId: number
  onSelectItem?: (itemId: number) => void
  title?: string
}

export default function ConflictDetector(props: ConflictDetectorProps) {
  const { projectId, onSelectItem, title: titleProp } = props
  const { t } = useTranslation()
  const title = titleProp ?? t('workflow.conflictDetector.title')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [duplicateNames, setDuplicateNames] = useState<DuplicateNameConflict[]>([])
  const [abilityMismatches, setAbilityMismatches] = useState<AbilityMismatchConflict[]>([])
  const [relationConflicts, setRelationConflicts] = useState<RelationConflict[]>([])
  const [totalConflicts, setTotalConflicts] = useState(0)
  const [hasDetected, setHasDetected] = useState(false)
  const relationConflictCount = relationConflicts.length

  useEffect(() => {
    if (projectId) {
      setHasDetected(false)
      setDuplicateNames([])
      setAbilityMismatches([])
      setRelationConflicts([])
      setTotalConflicts(0)
    }
  }, [projectId])

  const handleDetect = async () => {
    setLoading(true)
    setError(null)
    setHasDetected(false)

    try {
      const response = await apiClient.detectConflicts(projectId)
      const data = response.data

      setDuplicateNames(data.duplicate_names || [])
      setAbilityMismatches(data.ability_mismatches || [])
      setRelationConflicts(data.relation_conflicts || [])
      setTotalConflicts(data.total_conflicts || 0)
      setHasDetected(true)
    } catch (err: any) {
      setError(await extractApiErrorMessage(err, t('workflow.conflictDetector.detectFailed')))
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
        return t('workflow.conflictDetector.severityHigh')
      case 'medium':
        return t('workflow.conflictDetector.severityMedium')
      case 'low':
        return t('workflow.conflictDetector.severityLow')
      default:
        return t('workflow.conflictDetector.severityUnknown')
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
                label={totalConflicts > 0 ? t('workflow.conflictDetector.conflictCount', { count: totalConflicts }) : t('workflow.conflictDetector.noConflict')}
                size="small"
                color={totalConflicts > 0 ? 'warning' : 'success'}
              />
            )}
          </Box>
          <Tooltip title={t('workflow.conflictDetector.refresh')}>
            <IconButton size="small" onClick={handleDetect} disabled={loading}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>

        {!hasDetected && (
          <Box textAlign="center" py={3}>
            <Typography variant="body2" color="text.secondary" mb={2}>
              {t('workflow.conflictDetector.startHint')}
            </Typography>
            <Button
              variant="contained"
              color="primary"
              onClick={handleDetect}
              disabled={loading}
              startIcon={loading ? <CircularProgress size={16} /> : <WarningIcon />}
            >
              {loading ? t('workflow.conflictDetector.detecting') : t('workflow.conflictDetector.startDetect')}
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
              ✅ {t('workflow.conflictDetector.allClear')}
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
                  {t('workflow.conflictDetector.duplicateNameSection', { count: duplicateNames.length })}
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
                              {t('workflow.conflictDetector.itemCount', { count: conflict.items.length })}
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
                  {t('workflow.conflictDetector.abilityMismatchSection', { count: abilityMismatches.length })}
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
                                {t('workflow.conflictDetector.usesTechnique', { character: conflict.character, technique: conflict.technique })}
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
                                {t('workflow.conflictDetector.currentRealm', { realm: conflict.character_realm || t('workflow.conflictDetector.unset') })}
                              </Typography>
                              <Typography variant="caption" display="block" color="error.main">
                                {t('workflow.conflictDetector.requiredRealm', { realm: conflict.required_realm })}
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

            {/* 关系冲突 */}
            {relationConflictCount > 0 && (
              <Box>
                <Typography variant="subtitle2" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <ErrorOutlineIcon fontSize="small" color="error" />
                  {t('workflow.conflictDetector.relationSection', { count: relationConflictCount })}
                </Typography>
                <List dense>
                  {relationConflicts.map((conflict, index) => (
                    <Box key={index}>
                      <ListItem
                        sx={{
                          py: 1.5,
                          bgcolor: 'error.light',
                          borderRadius: 1,
                          mb: 1,
                        }}
                      >
                        <ListItemText
                          primary={
                            <Box display="flex" alignItems="center" gap={1} mb={0.5}>
                              <Typography variant="body2" fontWeight={500}>
                                {conflict.source} ↔ {conflict.target}
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
                                {conflict.description}
                              </Typography>
                              <Box display="flex" gap={1} mt={0.5}>
                                <Chip label={`${conflict.source}→${conflict.target}: ${conflict.forward_relation}`} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
                                <Chip label={`${conflict.target}→${conflict.source}: ${conflict.reverse_relation}`} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
                              </Box>
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
