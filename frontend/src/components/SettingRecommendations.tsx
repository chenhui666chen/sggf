import { useEffect, useState } from 'react'
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

const CATEGORY_LABELS: Record<string, string> = {
  all: '全部',
  map_system: '地图体系',
  cultivation_realm_system: '修仙境界体系',
  martial_realm_system: '武道境界体系',
  technique_system: '功法体系',
  pill_system: '丹药体系',
  formation_system: '阵法体系',
  talisman_system: '符箓体系',
  weapon_system: '法宝体系',
  resource_system: '资源体系',
  organization_force_system: '势力体系',
  ability_system: '异能体系',
  ability_realm_system: '异能境界体系',
  network_social_relationship_system: '人脉关系体系',
  special_artifact_relic_system: '道具遗物体系',
  wealth_business_empire_system: '财富商业体系',
  magic_realm_system: '魔法境界体系',
  magic_system: '魔法体系',
  race_bloodline_system: '种族血脉体系',
  profession_class_system: '职业体系',
  interstellar_travel_exploration_system: '星际航行体系',
  ai_robot_system: 'AI机器人体系',
  survivor_settlement_order_system: '聚落秩序体系',
  mutation_infection_aberration_system: '变异感染体系',
  skill_talent_system: '技能天赋体系',
  character_system: '角色体系',
  power_official_system: '权力官制体系',
  military_warfare_system: '军事战争体系',
  economy_taxation_system: '经济财税体系',
  culture_etiquette_examination_system: '文化礼制体系',
  legal_criminal_system: '律法刑罚体系',
  communication_intelligence_system: '通讯情报体系',
  historical_event_legend_system: '历史传说体系',
  lifestyle_custom_system: '民生风俗体系',
}

export default function SettingRecommendations(props: SettingRecommendationsProps) {
  const {
    projectId,
    onSelectItem,
    onInsertItem,
    showInsertButton = true,
    limit = 10,
    defaultCategory,
    title = '推荐设定',
  } = props

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
      setError(await extractApiErrorMessage(err, '加载失败'))
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
    if (!timestamp) return '未使用'

    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return '今天'
    if (diffDays === 1) return '1天前'
    if (diffDays < 30) return `${diffDays}天前`
    if (diffDays < 365) return `${Math.floor(diffDays / 30)}个月前`
    return `${Math.floor(diffDays / 365)}年前`
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
              <Chip label={`共${totalItems}项`} size="small" variant="outlined" />
            )}
          </Box>
          <IconButton size="small" onClick={loadRecommendations} disabled={loading}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Box>

        <Box mb={2}>
          <FormControl fullWidth size="small">
            <InputLabel>类型筛选</InputLabel>
            <Select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              label="类型筛选"
            >
              {categoryOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
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
              暂无推荐设定
            </Typography>
            <Typography variant="caption" color="text.secondary" textAlign="center" display="block" mt={1}>
              开始创作章节后，系统会自动推荐常用设定
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
                        label={`分数: ${item.score}`}
                        size="small"
                        color={getScoreColor(item.score)}
                        sx={{ height: 20 }}
                      />
                    </Box>

                    <Box display="flex" alignItems="center" gap={1} mb={0.5}>
                      <Chip
                        label={CATEGORY_LABELS[item.category] || item.collection_name}
                        size="small"
                        variant="outlined"
                        sx={{ height: 20, fontSize: '0.7rem' }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        使用 {item.usage_count} 次
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
                    <Tooltip title="查看详情">
                      <IconButton
                        size="small"
                        onClick={() => handleView(item)}
                        sx={{ width: 28, height: 28 }}
                      >
                        <VisibilityIcon sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Tooltip>
                    {showInsertButton && onInsertItem && (
                      <Tooltip title="插入到编辑器">
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
