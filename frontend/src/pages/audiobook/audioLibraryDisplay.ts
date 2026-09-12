/** i18next 翻译函数轻量接口：TFunction 带品牌属性，测试 mock 与真实 t 均兼容 */
export type TranslateFn = (key: string, options?: Record<string, unknown>) => string

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

export interface AudioAssetDescriptionSource {
  name?: string
  description?: string
  tags?: string[]
}

const AUDIO_KEYWORD_KEYS: Record<string, string> = {
  action: 'audiobook.audioLibraryDisplay.keywords.action',
  alchemy: 'audiobook.audioLibraryDisplay.keywords.alchemy',
  ambient: 'audiobook.audioLibraryDisplay.keywords.ambient',
  ambience: 'audiobook.audioLibraryDisplay.keywords.ambience',
  arcane: 'audiobook.audioLibraryDisplay.keywords.arcane',
  arrow: 'audiobook.audioLibraryDisplay.keywords.arrow',
  battle: 'audiobook.audioLibraryDisplay.keywords.battle',
  book: 'audiobook.audioLibraryDisplay.keywords.book',
  bottle: 'audiobook.audioLibraryDisplay.keywords.bottle',
  cork: 'audiobook.audioLibraryDisplay.keywords.cork',
  calm: 'audiobook.audioLibraryDisplay.keywords.calm',
  city: 'audiobook.audioLibraryDisplay.keywords.city',
  clinic: 'audiobook.audioLibraryDisplay.keywords.clinic',
  close: 'audiobook.audioLibraryDisplay.keywords.close',
  detail: 'audiobook.audioLibraryDisplay.keywords.detail',
  dice: 'audiobook.audioLibraryDisplay.keywords.dice',
  die: 'audiobook.audioLibraryDisplay.keywords.die',
  door: 'audiobook.audioLibraryDisplay.keywords.door',
  emotion: 'audiobook.audioLibraryDisplay.keywords.emotion',
  environment: 'audiobook.audioLibraryDisplay.keywords.environment',
  epic: 'audiobook.audioLibraryDisplay.keywords.epic',
  fantasy: 'audiobook.audioLibraryDisplay.keywords.fantasy',
  fast: 'audiobook.audioLibraryDisplay.keywords.fast',
  feathers: 'audiobook.audioLibraryDisplay.keywords.feathers',
  fire: 'audiobook.audioLibraryDisplay.keywords.fire',
  footstep: 'audiobook.audioLibraryDisplay.keywords.footstep',
  footsteps: 'audiobook.audioLibraryDisplay.keywords.footsteps',
  general: 'audiobook.audioLibraryDisplay.keywords.general',
  glass: 'audiobook.audioLibraryDisplay.keywords.glass',
  gambling: 'audiobook.audioLibraryDisplay.keywords.gambling',
  heartbeat: 'audiobook.audioLibraryDisplay.keywords.heartbeat',
  horn: 'audiobook.audioLibraryDisplay.keywords.horn',
  hit: 'audiobook.audioLibraryDisplay.keywords.hit',
  horror: 'audiobook.audioLibraryDisplay.keywords.horror',
  impact: 'audiobook.audioLibraryDisplay.keywords.impact',
  indoor: 'audiobook.audioLibraryDisplay.keywords.indoor',
  intense: 'audiobook.audioLibraryDisplay.keywords.intense',
  joyful: 'audiobook.audioLibraryDisplay.keywords.joyful',
  jump: 'audiobook.audioLibraryDisplay.keywords.jump',
  long: 'audiobook.audioLibraryDisplay.keywords.long',
  machine: 'audiobook.audioLibraryDisplay.keywords.machine',
  custom: 'audiobook.audioLibraryDisplay.keywords.custom',
  alarm: 'audiobook.audioLibraryDisplay.keywords.alarm',
  medium: 'audiobook.audioLibraryDisplay.keywords.medium',
  medicine: 'audiobook.audioLibraryDisplay.keywords.medicine',
  metal: 'audiobook.audioLibraryDisplay.keywords.metal',
  mysterious: 'audiobook.audioLibraryDisplay.keywords.mysterious',
  mystery: 'audiobook.audioLibraryDisplay.keywords.mystery',
  odd: 'audiobook.audioLibraryDisplay.keywords.odd',
  outdoor: 'audiobook.audioLibraryDisplay.keywords.outdoor',
  page: 'audiobook.audioLibraryDisplay.keywords.page',
  paper: 'audiobook.audioLibraryDisplay.keywords.paper',
  phase: 'audiobook.audioLibraryDisplay.keywords.phase',
  pill: 'audiobook.audioLibraryDisplay.keywords.pill',
  peaceful: 'audiobook.audioLibraryDisplay.keywords.peaceful',
  people: 'audiobook.audioLibraryDisplay.keywords.people',
  passenger: 'audiobook.audioLibraryDisplay.keywords.passenger',
  passengers: 'audiobook.audioLibraryDisplay.keywords.passengers',
  platform: 'audiobook.audioLibraryDisplay.keywords.platform',
  public_transport: 'audiobook.audioLibraryDisplay.keywords.public_transport',
  rain: 'audiobook.audioLibraryDisplay.keywords.rain',
  reading: 'audiobook.audioLibraryDisplay.keywords.reading',
  realistic: 'audiobook.audioLibraryDisplay.keywords.realistic',
  romantic: 'audiobook.audioLibraryDisplay.keywords.romantic',
  romance: 'audiobook.audioLibraryDisplay.keywords.romance',
  room: 'audiobook.audioLibraryDisplay.keywords.room',
  rustle: 'audiobook.audioLibraryDisplay.keywords.rustle',
  ritual: 'audiobook.audioLibraryDisplay.keywords.ritual',
  roll: 'audiobook.audioLibraryDisplay.keywords.roll',
  sad: 'audiobook.audioLibraryDisplay.keywords.sad',
  scifi: 'audiobook.audioLibraryDisplay.keywords.scifi',
  sci_fi: 'audiobook.audioLibraryDisplay.keywords.sci_fi',
  shake: 'audiobook.audioLibraryDisplay.keywords.shake',
  slow: 'audiobook.audioLibraryDisplay.keywords.slow',
  sting: 'audiobook.audioLibraryDisplay.keywords.sting',
  single: 'audiobook.audioLibraryDisplay.keywords.single',
  storm: 'audiobook.audioLibraryDisplay.keywords.storm',
  tense: 'audiobook.audioLibraryDisplay.keywords.tense',
  thud: 'audiobook.audioLibraryDisplay.keywords.thud',
  thunder: 'audiobook.audioLibraryDisplay.keywords.thunder',
  transition: 'audiobook.audioLibraryDisplay.keywords.transition',
  train: 'audiobook.audioLibraryDisplay.keywords.train',
  railway: 'audiobook.audioLibraryDisplay.keywords.railway',
  locomotive: 'audiobook.audioLibraryDisplay.keywords.locomotive',
  station: 'audiobook.audioLibraryDisplay.keywords.station',
  travel: 'audiobook.audioLibraryDisplay.keywords.travel',
  table: 'audiobook.audioLibraryDisplay.keywords.table',
  talk: 'audiobook.audioLibraryDisplay.keywords.talk',
  talking: 'audiobook.audioLibraryDisplay.keywords.talking',
  tavern: 'audiobook.audioLibraryDisplay.keywords.tavern',
  twist: 'audiobook.audioLibraryDisplay.keywords.twist',
  two: 'audiobook.audioLibraryDisplay.keywords.two',
  uncork: 'audiobook.audioLibraryDisplay.keywords.uncork',
  water: 'audiobook.audioLibraryDisplay.keywords.water',
  weird: 'audiobook.audioLibraryDisplay.keywords.weird',
  wood: 'audiobook.audioLibraryDisplay.keywords.wood',
}

const AUDIO_ASSET_NAME_PHRASE_KEYS: Record<string, string> = {
  book_page: 'audiobook.audioLibraryDisplay.phrases.book_page',
  glass_瓶子_cork_twist: 'audiobook.audioLibraryDisplay.phrases.glass_bottle_cork_twist',
  glass_瓶子_uncork: 'audiobook.audioLibraryDisplay.phrases.glass_bottle_uncork',
  medicine_pill: 'audiobook.audioLibraryDisplay.phrases.medicine_pill',
  single_die_roll_table: 'audiobook.audioLibraryDisplay.phrases.single_die_roll_table',
  train_horn_airchime_k5la: 'audiobook.audioLibraryDisplay.phrases.train_horn_airchime_k5la',
  two_dice_roll_table: 'audiobook.audioLibraryDisplay.phrases.two_dice_roll_table',
}

const SOURCE_KEYS: Record<string, string> = {
  aliyun_oss: 'audiobook.audioLibraryDisplay.sources.aliyun_oss',
  dashscope_oss: 'audiobook.audioLibraryDisplay.sources.dashscope_oss',
  local_authorized: 'audiobook.audioLibraryDisplay.sources.local_authorized',
  local_cache: 'audiobook.audioLibraryDisplay.sources.local_cache',
  mureka: 'audiobook.audioLibraryDisplay.sources.mureka',
  vidu: 'audiobook.audioLibraryDisplay.sources.vidu',
}

const QUALITY_STATUS_KEYS: Record<string, string> = {
  accepted: 'audiobook.audioLibraryDisplay.qualityStatuses.accepted',
  rejected: 'audiobook.audioLibraryDisplay.qualityStatuses.rejected',
  tolerated: 'audiobook.audioLibraryDisplay.qualityStatuses.tolerated',
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

const splitAudioTokens = (value: string) =>
  value.trim().split(/[._\s-]+/).filter(Boolean)

const translateAudioTokens = (value: string, t: TranslateFn) => {
  const labels = splitAudioTokens(value)
    .map((token) => {
      if (hasChinese(token) && !/[A-Za-z]/.test(token)) return token
      const key = AUDIO_KEYWORD_KEYS[normalizeKeyword(token)]
      return key ? t(key) : ''
    })
    .filter(Boolean)
  return labels.filter((label, index) => label !== labels[index - 1])
}

export const formatAudioKeywordLabel = (value: string | null | undefined, t: TranslateFn) => {
  const raw = String(value || '').trim()
  if (!raw) return t('audiobook.audioLibraryDisplay.uncategorized')
  if (hasChinese(raw) && !/[A-Za-z]/.test(raw)) return raw
  const exactKey = AUDIO_KEYWORD_KEYS[normalizeKeyword(raw)]
  if (exactKey) return t(exactKey)
  const labels = translateAudioTokens(raw, t)
  return labels.length > 0 ? labels.join('') : t('audiobook.audioLibraryDisplay.other')
}

export const formatAudioAssetNameLabel = (name: string | null | undefined, t: TranslateFn) => {
  const raw = String(name || '').trim()
  if (!raw) return t('audiobook.audioLibraryDisplay.unnamedAsset')
  const exactPhraseKey = AUDIO_ASSET_NAME_PHRASE_KEYS[normalizeKeyword(raw)]
  if (exactPhraseKey) return t(exactPhraseKey)
  const parts = splitAudioTokens(raw)
  const labels: string[] = []

  for (let index = 0; index < parts.length; index += 1) {
    const phraseKey = normalizeKeyword(parts.slice(index, index + 2).join('_'))
    if (AUDIO_ASSET_NAME_PHRASE_KEYS[phraseKey]) {
      labels.push(t(AUDIO_ASSET_NAME_PHRASE_KEYS[phraseKey]))
      index += 1
      continue
    }

    const part = parts[index]
    if (/^\d+$/.test(part)) {
      labels.push(part)
      continue
    }
    if (hasChinese(part) && !/[A-Za-z]/.test(part)) {
      labels.push(part)
      continue
    }
    if (hasChinese(part)) {
      // 中英混合片段：提取中文部分展示，避免整段被丢弃后兜底“其他音效”
      const chineseOnly = (part.match(/[\u4e00-\u9fff]+/g) || []).join('')
      if (chineseOnly) {
        labels.push(chineseOnly)
        continue
      }
    }
    const key = AUDIO_KEYWORD_KEYS[normalizeKeyword(part)]
    if (key) labels.push(t(key))
  }

  const localized = labels
    .filter((label, index) => label !== labels[index - 1])
    .join(' ')
  return localized || t('audiobook.audioLibraryDisplay.otherSfx')
}

export const formatAudioAssetDescriptionLabel = ({
  name,
  description,
  tags = [],
}: AudioAssetDescriptionSource, t: TranslateFn) => {
  const rawDescription = String(description || '').trim()
  if (hasChinese(rawDescription) && !/[A-Za-z]/.test(rawDescription)) return rawDescription

  const semanticText = `${name || ''} ${rawDescription} ${tags.join(' ')}`.toLowerCase()
  const hasTrain = /\b(train|railway|locomotive)\b/.test(semanticText)
  const hasHorn = /\b(horn|airchime)\b/.test(semanticText)
  const hasPeople = /\b(people|passengers?|talk|talking|crowd|announcement)\b/.test(semanticText)
  if (hasTrain && hasHorn && hasPeople) {
    return t('audiobook.audioLibraryDisplay.trainStationDescription')
  }
  if (hasTrain && hasHorn) return t('audiobook.audioLibraryDisplay.trainHornDescription')
  if (/\bmetal\b/.test(semanticText) && /\b(hit|impact|strike)\b/.test(semanticText)) {
    return t('audiobook.audioLibraryDisplay.metalHitDescription')
  }
  if (/\bwood\b/.test(semanticText) && /\b(hit|impact|strike)\b/.test(semanticText)) {
    return t('audiobook.audioLibraryDisplay.woodHitDescription')
  }

  const nameLabel = formatAudioAssetNameLabel(name, t)
  return nameLabel === t('audiobook.audioLibraryDisplay.otherSfx') || nameLabel === t('audiobook.audioLibraryDisplay.unnamedAsset') ? '' : `${nameLabel}。`
}

export const formatSfxCategoryLabel = (category: string | null | undefined, t: TranslateFn) => {
  const raw = String(category || '').trim()
  if (!raw) return t('audiobook.audioLibraryDisplay.uncategorized')
  return raw.split('/').map((segment) => formatAudioKeywordLabel(segment, t)).join(' / ')
}

export const formatMusicDurationLabel = (duration: number | null | undefined, t: TranslateFn) => {
  if (typeof duration !== 'number' || !Number.isFinite(duration)) return t('audiobook.audioLibraryDisplay.durationUnknown')
  return t('audiobook.audioLibraryDisplay.durationSeconds', { count: Math.round(duration) })
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

export const formatSourceLabel = (source: string | null | undefined, t: TranslateFn) => {
  const raw = String(source || '').trim()
  if (!raw) return t('audiobook.audioLibraryDisplay.local')
  const key = SOURCE_KEYS[normalizeKeyword(raw)]
  return key ? t(key) : t('audiobook.audioLibraryDisplay.otherSource')
}

const formatQualityStatusLabel = (status: string | undefined, t: TranslateFn) => {
  if (!status) return ''
  const key = QUALITY_STATUS_KEYS[normalizeKeyword(status)]
  return key ? t(key) : formatAudioKeywordLabel(status, t)
}

const formatQualityDetailValue = (entry: AudioLibraryDetailSource, t: TranslateFn) => {
  const score = typeof entry.quality_score === 'number' && Number.isFinite(entry.quality_score)
    ? entry.quality_score.toFixed(1)
    : t('audiobook.audioLibraryDisplay.unscored')
  const grade = entry.quality_grade ? ` / ${entry.quality_grade}` : ''
  const status = entry.quality_status ? ` ${formatQualityStatusLabel(entry.quality_status, t)}` : ''
  return `${score}${grade}${status}`
}

export const formatCommercialLabel = (entry: AudioLibraryDetailSource, t: TranslateFn) => {
  if (entry.license_commercial === true) return t('audiobook.audioLibraryDisplay.commercialAllowed')
  if (entry.license_commercial === false) return t('audiobook.audioLibraryDisplay.commercialNotAllowed')
  return t('audiobook.audioLibraryDisplay.commercialUnknown')
}

export const formatAttributionLabel = (entry: AudioLibraryDetailSource, t: TranslateFn) => {
  if (entry.attribution_required === true) return t('audiobook.audioLibraryDisplay.attributionRequired')
  if (entry.attribution_required === false) return t('audiobook.audioLibraryDisplay.attributionFree')
  return t('audiobook.audioLibraryDisplay.attributionUnknown')
}

export const formatDateLabel = (value?: string) => {
  if (!value) return ''
  return value.slice(0, 10)
}

export const buildAudioLibraryDetailItems = (entry: AudioLibraryDetailSource, t: TranslateFn) => {
  const items: AudioLibraryDetailItem[] = []

  if (
    typeof entry.quality_score === 'number'
    || Boolean(entry.quality_grade)
    || Boolean(entry.quality_status)
  ) {
    items.push({ key: 'quality', label: t('audiobook.audioLibraryDisplay.labelQuality'), value: formatQualityDetailValue(entry, t) })
  }

  if (entry.license || entry.license_url) {
    items.push({
      key: 'license',
      label: t('audiobook.audioLibraryDisplay.labelLicense'),
      value: entry.license || t('audiobook.audioLibraryDisplay.notRecorded'),
      title: entry.license_url || undefined,
    })
  }

  if (entry.license_commercial !== undefined) {
    items.push({ key: 'commercial', label: t('audiobook.audioLibraryDisplay.labelCommercial'), value: formatCommercialLabel(entry, t) })
  }

  if (entry.attribution_required !== undefined) {
    items.push({ key: 'attribution', label: t('audiobook.audioLibraryDisplay.labelAttribution'), value: formatAttributionLabel(entry, t) })
  }

  if (entry.author) {
    items.push({
      key: 'author',
      label: t('audiobook.audioLibraryDisplay.labelAuthor'),
      value: entry.author,
      title: entry.author_url || undefined,
    })
  }

  if (entry.source || entry.source_url || entry.source_id) {
    items.push({
      key: 'source',
      label: t('audiobook.audioLibraryDisplay.labelSource'),
      value: formatSourceLabel(entry.source, t),
      title: entry.source_url || entry.source_id || undefined,
    })
  }

  if (entry.retrieved_at) {
    items.push({ key: 'retrieved_at', label: t('audiobook.audioLibraryDisplay.labelRetrievedAt'), value: formatDateLabel(entry.retrieved_at) })
  }

  if (entry.license_checked_at) {
    items.push({
      key: 'license_checked_at',
      label: t('audiobook.audioLibraryDisplay.labelLicenseCheckedAt'),
      value: formatDateLabel(entry.license_checked_at),
    })
  }

  if (entry.attribution_text) {
    items.push({ key: 'attribution_text', label: t('audiobook.audioLibraryDisplay.labelAttributionText'), value: entry.attribution_text })
  }

  return items
}
