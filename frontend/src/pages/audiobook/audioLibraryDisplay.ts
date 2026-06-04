export interface AudioLibraryDetailSource {
  source?: string
  source_id?: string
  source_url?: string
  author?: string
  author_url?: string
  license?: string
  license_url?: string
  license_commercial?: boolean
  attribution_required?: boolean
  attribution_text?: string
  quality_score?: number
  quality_grade?: string
  quality_status?: string
  retrieved_at?: string
  license_checked_at?: string
}

export interface AudioLibraryDetailItem {
  key: string
  label: string
  value: string
  title?: string
}

const AUDIO_KEYWORD_LABELS: Record<string, string> = {
  action: '动作',
  alchemy: '炼金',
  ambient: '氛围',
  ambience: '氛围',
  arcane: '奥术',
  arrow: '箭矢',
  battle: '战斗',
  book: '书页',
  bottle: '瓶子',
  calm: '平静',
  city: '城市',
  clinic: '诊所',
  close: '合上',
  detail: '细节',
  door: '门',
  emotion: '情绪',
  environment: '环境',
  epic: '史诗',
  fantasy: '奇幻',
  fast: '快节奏',
  feathers: '羽毛',
  fire: '火焰',
  footstep: '脚步',
  footsteps: '脚步',
  general: '通用',
  heartbeat: '心跳',
  hit: '撞击',
  horror: '惊悚',
  impact: '撞击',
  indoor: '室内',
  intense: '强烈',
  joyful: '欢快',
  jump: '跳跃',
  long: '长版',
  machine: '机器',
  medium: '中速',
  medicine: '医药',
  metal: '金属',
  mysterious: '神秘',
  mystery: '悬疑',
  odd: '诡异',
  outdoor: '室外',
  page: '书页',
  paper: '纸张',
  phase: '相位',
  pill: '药片',
  peaceful: '平静',
  people: '人群',
  rain: '雨声',
  reading: '阅读',
  realistic: '写实',
  romantic: '浪漫',
  romance: '浪漫',
  room: '房间',
  rustle: '摩擦',
  sad: '悲伤',
  scifi: '科幻',
  sci_fi: '科幻',
  shake: '摇晃',
  slow: '慢速',
  sting: '刺点',
  storm: '暴风雨',
  tense: '紧张',
  thud: '闷响',
  thunder: '雷声',
  transition: '转场',
  travel: '旅行',
  water: '水声',
  weird: '诡异',
  wood: '木头',
}

const AUDIO_ASSET_NAME_PHRASES: Record<string, string> = {
  book_page: '书页',
  medicine_pill: '药片',
}

const SOURCE_LABELS: Record<string, string> = {
  aliyun_oss: '阿里云 OSS',
  dashscope_oss: 'DashScope OSS',
  local_authorized: '本地授权素材',
  local_cache: '本地缓存',
  mureka: 'Mureka 生成',
  vidu: 'Vidu 生成',
}

const QUALITY_STATUS_LABELS: Record<string, string> = {
  accepted: '已通过',
  rejected: '未通过',
  tolerated: '可用',
}

const COMPLIANCE_TAG_KEYS = new Set([
  'attribution',
  'attribution_required',
  'cc0',
  'cc_by',
  'commercial',
  'license',
  'license_commercial',
  'local_authorized',
  'noncommercial',
  'public_domain',
  'source',
])

const GENERATED_SCENE_PATTERN = /^scene[_\s-]*\d+$/i

const normalizeKeyword = (value: string) =>
  value.trim().toLowerCase().replace(/[-\s]+/g, '_')

const hasChinese = (value: string) => /[\u4e00-\u9fff]/.test(value)

const formatUnknownKeyword = (value: string) =>
  value.trim().replace(/[._-]+/g, ' ').replace(/\s+/g, ' ')

export const formatAudioKeywordLabel = (value?: string | null) => {
  const raw = String(value || '').trim()
  if (!raw) return '未分类'
  if (hasChinese(raw)) return raw
  return AUDIO_KEYWORD_LABELS[normalizeKeyword(raw)] || formatUnknownKeyword(raw)
}

export const formatAudioAssetNameLabel = (name?: string | null) => {
  const raw = String(name || '').trim()
  if (!raw) return '未命名素材'
  if (hasChinese(raw)) return raw
  const parts = raw.split(/[_\s-]+/).filter(Boolean)
  const labels: string[] = []

  for (let index = 0; index < parts.length; index += 1) {
    const phraseKey = normalizeKeyword(parts.slice(index, index + 2).join('_'))
    if (AUDIO_ASSET_NAME_PHRASES[phraseKey]) {
      labels.push(AUDIO_ASSET_NAME_PHRASES[phraseKey])
      index += 1
      continue
    }

    const part = parts[index]
    labels.push(/^\d+$/.test(part) ? part : formatAudioKeywordLabel(part))
  }

  return labels
    .filter((label, index) => label !== labels[index - 1])
    .join(' ')
}

export const formatSfxCategoryLabel = (category?: string | null) => {
  const raw = String(category || '').trim()
  if (!raw) return '未分类'
  return raw.split('/').map(formatAudioKeywordLabel).join(' / ')
}

export const formatMusicDurationLabel = (duration?: number | null) => {
  if (typeof duration !== 'number' || !Number.isFinite(duration)) return '时长未知'
  return `${Math.round(duration)} 秒`
}

export const getVisibleSfxTags = (tags: string[] = []) =>
  tags.filter((tag) => {
    const key = normalizeKeyword(tag)
    return Boolean(key) && !COMPLIANCE_TAG_KEYS.has(key)
  })

export const getVisibleSfxScenes = (scenes: string[] = []) =>
  scenes.filter((scene) => {
    const raw = String(scene || '').trim()
    return Boolean(raw) && !GENERATED_SCENE_PATTERN.test(raw)
  })

export const formatSourceLabel = (source?: string | null) => {
  const raw = String(source || '').trim()
  if (!raw) return '本地'
  return SOURCE_LABELS[normalizeKeyword(raw)] || formatUnknownKeyword(raw)
}

const formatQualityStatusLabel = (status?: string) => {
  if (!status) return ''
  return QUALITY_STATUS_LABELS[normalizeKeyword(status)] || formatAudioKeywordLabel(status)
}

const formatQualityDetailValue = (entry: AudioLibraryDetailSource) => {
  const score = typeof entry.quality_score === 'number' && Number.isFinite(entry.quality_score)
    ? entry.quality_score.toFixed(1)
    : '未评分'
  const grade = entry.quality_grade ? ` / ${entry.quality_grade}` : ''
  const status = entry.quality_status ? ` ${formatQualityStatusLabel(entry.quality_status)}` : ''
  return `${score}${grade}${status}`
}

export const formatCommercialLabel = (entry: AudioLibraryDetailSource) => {
  if (entry.license_commercial === true) return '允许商用'
  if (entry.license_commercial === false) return '非商用'
  return '商用未知'
}

export const formatAttributionLabel = (entry: AudioLibraryDetailSource) => {
  if (entry.attribution_required === true) return '需署名'
  if (entry.attribution_required === false) return '免署名'
  return '署名未知'
}

export const formatDateLabel = (value?: string) => {
  if (!value) return ''
  return value.slice(0, 10)
}

export const buildAudioLibraryDetailItems = (entry: AudioLibraryDetailSource) => {
  const items: AudioLibraryDetailItem[] = []

  if (
    typeof entry.quality_score === 'number'
    || Boolean(entry.quality_grade)
    || Boolean(entry.quality_status)
  ) {
    items.push({ key: 'quality', label: '质量', value: formatQualityDetailValue(entry) })
  }

  if (entry.license || entry.license_url) {
    items.push({
      key: 'license',
      label: '授权',
      value: entry.license || '未记录',
      title: entry.license_url || undefined,
    })
  }

  if (entry.license_commercial !== undefined) {
    items.push({ key: 'commercial', label: '商用', value: formatCommercialLabel(entry) })
  }

  if (entry.attribution_required !== undefined) {
    items.push({ key: 'attribution', label: '署名', value: formatAttributionLabel(entry) })
  }

  if (entry.author) {
    items.push({
      key: 'author',
      label: '作者',
      value: entry.author,
      title: entry.author_url || undefined,
    })
  }

  if (entry.source || entry.source_url || entry.source_id) {
    items.push({
      key: 'source',
      label: '来源',
      value: formatSourceLabel(entry.source),
      title: entry.source_url || entry.source_id || undefined,
    })
  }

  if (entry.retrieved_at) {
    items.push({ key: 'retrieved_at', label: '入库', value: formatDateLabel(entry.retrieved_at) })
  }

  if (entry.license_checked_at) {
    items.push({
      key: 'license_checked_at',
      label: '授权检查',
      value: formatDateLabel(entry.license_checked_at),
    })
  }

  if (entry.attribution_text) {
    items.push({ key: 'attribution_text', label: '授权说明', value: entry.attribution_text })
  }

  return items
}
