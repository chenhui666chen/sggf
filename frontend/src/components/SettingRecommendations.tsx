import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Card,
  CardContent,
  Typography,
  IconButton,
  Chip,
  Stack,
  CircularProgress,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  Tooltip,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import VisibilityIcon from '@mui/icons-material/Visibility'
import AddIcon from '@mui/icons-material/Add'
import StarIcon from '@mui/icons-material/Star'
import { apiClient, extractApiErrorMessage } from '@/services/api'

interface SettingRecommendation {
  id: number
  name: string
  collection_id: number
  collection_name: string
  category: string
  usage_count: number
  last_referenced_at: string | null
  score: number
  content_preview?: string
  tags?: string[]
}

interface SettingRecommendationsProps {
  projectId: number
  onSelectItem?: (item: SettingRecommendation) => void
  onInsertItem?: (item: SettingRecommendation) => void
  showInsertButton?: boolean
  limit?: number
  defaultCategory?: string
  title?: string
}

// value 为后端 category 代码（提交值不可翻译），label 值为 i18n key，渲染处 t(labelKey)
const CATEGORY_LABELS: Record<string, string> = {
  all: 'settingRecommendations.categoryAll',
  map_system: 'settingRecommendations.categoryMapSystem',
  cultivation_realm_system: 'settingRecommendations.categoryCultivationRealmSystem',
  martial_realm_system: 'settingRecommendations.categoryMartialRealmSystem',
  technique_system: 'settingRecommendations.categoryTechniqueSystem',
  pill_system: 'settingRecommendations.categoryPillSystem',
  formation_system: 'settingRecommendations.categoryFormationSystem',
  talisman_system: 'settingRecommendations.categoryTalismanSystem',
  weapon_system: 'settingRecommendations.categoryWeaponSystem',
  resource_system: 'settingRecommendations.categoryResourceSystem',
  organization_force_system: 'settingRecommendations.categoryOrganizationForceSystem',
  ability_system: 'settingRecommendations.categoryAbilitySystem',
  ability_realm_system: 'settingRecommendations.categoryAbilityRealmSystem',
  network_social_relationship_system: 'settingRecommendations.categoryNetworkSocialRelationshipSystem',
  special_artifact_relic_system: 'settingRecommendations.categorySpecialArtifactRelicSystem',
  wealth_business_empire_system: 'settingRecommendations.categoryWealthBusinessEmpireSystem',
  magic_realm_system: 'settingRecommendations.categoryMagicRealmSystem',
  magic_system: 'settingRecommendations.categoryMagicSystem',
  race_bloodline_system: 'settingRecommendations.categoryRaceBloodlineSystem',
  profession_class_system: 'settingRecommendations.categoryProfessionClassSystem',
  interstellar_travel_exploration_system: 'settingRecommendations.categoryInterstellarTravelExplorationSystem',
  ai_robot_system: 'settingRecommendations.categoryAiRobotSystem',
  survivor_settlement_order_system: 'settingRecommendations.categorySurvivorSettlementOrderSystem',
  mutation_infection_aberration_system: 'settingRecommendations.categoryMutationInfectionAberrationSystem',
  skill_talent_system: 'settingRecommendations.categorySkillTalentSystem',
  character_system: 'settingRecommendations.categoryCharacterSystem',
  power_official_system: 'settingRecommendations.categoryPowerOfficialSystem',
  military_warfare_system: 'settingRecommendations.categoryMilitaryWarfareSystem',
  economy_taxation_system: 'settingRecommendations.categoryEconomyTaxationSystem',
  culture_etiquette_examination_system: 'settingRecommendations.categoryCultureEtiquetteExaminationSystem',
  legal_criminal_system: 'settingRecommendations.categoryLegalCriminalSystem',
  communication_intelligence_system: 'settingRecommendations.categoryCommunicationIntelligenceSystem',
  historical_event_legend_system: 'settingRecommendations.categoryHistoricalEventLegendSystem',
  lifestyle_custom_system: 'settingRecommendations.categoryLifestyleCustomSystem',
}

export default function SettingRecommendations(props: SettingRecommendationsProps) {
  const {
    projectId,
    onSelectItem,
    onInsertItem,
    showInsertButton = true,
    limit = 10,
    defaultCategory,
    title: titleProp,
  } = props
  const { t } = useTranslation()
  const title = titleProp ?? t('settingRecommendations.title')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [recommendations, setRecommendations] = useState<SettingRecommendation[]>([])
  const [category, setCategory] = useState<string>(defaultCategory || 'all')
  const [totalItems, setTotalItems] = useState(0)
  const categoryOptions = Object.entries(CATEGORY_LABELS).map(([value, label]) => ({
    value,
    label,
  }))

  const loadRecommendations = async () => {
    if (!projectId) return

    setLoading(true)
    setError(null)

    try {
      const categoryParam = category === 'all' ? undefined : category
      const response = await apiClient.getSettingRecommendations(projectId, categoryParam, limit)
      const data = response.data

      setRecommendations(data.recommendations || [])
      setTotalItems(data.total_items || 0)
    } catch (err: any) {
      setError(await extractApiErrorMessage(err, t('settingRecommendations.loadFailed')))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRecommendations()
  }, [projectId, category, limit])

  const handleView = (item: SettingRecommendation) => {
    if (onSelectItem) {
      onSelectItem(item)
    }
  }

  const handleInsert = (item: SettingRecommendation) => {
    if (onInsertItem) {
      onInsertItem(item)
    }
  }

  const formatLastUsed = (timestamp: string | null) => {
    if (!timestamp) return t('settingRecommendations.neverUsed')

    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return t('settingRecommendations.today')
    if (diffDays === 1) return t('settingRecommendations.daysAgoOne')
    if (diffDays < 30) return t('settingRecommendations.daysAgoMany', { count: diffDays })
    if (diffDays < 365) return t('settingRecommendations.monthsAgoMany', { count: Math.floor(diffDays / 30) })
    return t('settingRecommendations.yearsAgoMany', { count: Math.floor(diffDays / 365) })
  }

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'success'
    if (score >= 0.5) return 'warning'
    return 'default'
  }

  return (
    <Card elevation={2}>
      <CardContent>
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
          <Box display="flex" alignItems="center" gap={1}>
            <StarIcon color="warning" />
            <Typography variant="h6" fontWeight={600}>
              {title}
            </Typography>
            {totalItems > 0 && (
              <Chip label={t('settingRecommendations.totalItems', { count: totalItems })} size="small" variant="outlined" />
            )}
          </Box>
          <IconButton size="small" onClick={loadRecommendations} disabled={loading}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Box>

        <Box mb={2}>
          <FormControl fullWidth size="small">
            <InputLabel>{t('settingRecommendations.categoryFilter')}</InputLabel>
            <Select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              label={t('settingRecommendations.categoryFilter')}
            >
              {categoryOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {t(option.label)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>

        {loading && (
          <Box display="flex" justifyContent="center" py={3}>
            <CircularProgress size={24} />
          </Box>
        )}

        {!loading && error && (
          <Box py={2}>
            <Typography variant="body2" color="error">
              {error}
            </Typography>
          </Box>
        )}

        {!loading && !error && recommendations.length === 0 && (
          <Box py={2}>
            <Typography variant="body2" color="text.secondary" textAlign="center">
              {t('settingRecommendations.emptyTitle')}
            </Typography>
            <Typography variant="caption" color="text.secondary" textAlign="center" display="block" mt={1}>
              {t('settingRecommendations.emptyHint')}
            </Typography>
          </Box>
        )}

        {!loading && !error && recommendations.length > 0 && (
          <Stack spacing={1.5}>
            {recommendations.map((item, index) => (
              <Box
                key={item.id}
                sx={{
                  p: 1.5,
                  border: '1px solid',
                  borderColor: 'grey.300',
                  borderRadius: 1,
                  '&:hover': {
                    bgcolor: 'grey.50',
                    borderColor: 'primary.main',
                  },
                  transition: 'all 0.2s',
                }}
              >
                <Box display="flex" alignItems="flex-start" justifyContent="space-between">
                  <Box flex={1}>
                    <Box display="flex" alignItems="center" gap={1} mb={0.5}>
                      <Typography variant="body2" fontWeight={600}>
                        {index + 1}. {item.name}
                      </Typography>
                      <Chip
                        label={t('settingRecommendations.scoreLabel', { score: item.score })}
                        size="small"
                        color={getScoreColor(item.score)}
                        sx={{ height: 20 }}
                      />
                    </Box>

                    <Box display="flex" alignItems="center" gap={1} mb={0.5}>
                      <Chip
                        label={CATEGORY_LABELS[item.category] ? t(CATEGORY_LABELS[item.category]) : item.collection_name}
                        size="small"
                        variant="outlined"
                        sx={{ height: 20, fontSize: '0.7rem' }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        {t('settingRecommendations.usageCount', { count: item.usage_count })}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        · {formatLastUsed(item.last_referenced_at)}
                      </Typography>
                    </Box>

                    {item.content_preview && (
                      <Tooltip title={item.content_preview} placement="top">
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{
                            display: '-webkit-box',
                            WebkitLineClamp: 1,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }}
                        >
                          {item.content_preview}
                        </Typography>
                      </Tooltip>
                    )}
                  </Box>

                  <Stack direction="row" spacing={0.5} ml={1}>
                    <Tooltip title={t('settingRecommendations.viewDetail')}>
                      <IconButton
                        size="small"
                        onClick={() => handleView(item)}
                        sx={{ width: 28, height: 28 }}
                      >
                        <VisibilityIcon sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Tooltip>
                    {showInsertButton && onInsertItem && (
                      <Tooltip title={t('settingRecommendations.insertToEditor')}>
                        <IconButton
                          size="small"
                          color="primary"
                          onClick={() => handleInsert(item)}
                          sx={{ width: 28, height: 28 }}
                        >
                          <AddIcon sx={{ fontSize: 16 }} />
                        </IconButton>
                      </Tooltip>
                    )}
                  </Stack>
                </Box>
              </Box>
            ))}
          </Stack>
        )}
      </CardContent>
    </Card>
  )
}
