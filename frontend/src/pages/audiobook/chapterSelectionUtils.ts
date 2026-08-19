import type { Chapter, ChapterAudio, ChapterRenderState } from './types'
import { CHAPTER_RENDER_STATUS } from './types'


export const resolveGeneratedChapterIds = (
  chapterAudios: readonly ChapterAudio[],
): Set<number> => {
  const generatedChapterIds = new Set<number>()
  for (const chapterAudio of chapterAudios) {
    const scriptStatus = String(chapterAudio.script_status || '').trim().toLowerCase()
    if (
      chapterAudio.has_script
      || Boolean(chapterAudio.audio_path)
      || scriptStatus === 'reviewed'
      || scriptStatus === 'approved'
    ) {
      generatedChapterIds.add(chapterAudio.chapter_id)
    }
  }
  return generatedChapterIds
}

/**
 * 两引擎完成条件（GUIDE §2.3/验收 9）：
 *
 * - legacy_stems：script_json + audio_path + script_status（旧完成条件）；
 * - seed_scene：三维投影 render_status 非空即视为已占用（rendered_all_seed/
 *   rendered_with_fallback/stale/manual_review_required/failed 均可进入工作台或
 *   场景编辑器重渲染，禁止覆盖式初始生成）；历史 seed 产物 render_status 保持
 *   null 时回退旧条件（legacy_unverified 可导出）。
 */
export const isChapterGeneratedForEngine = (
  chapterAudio: ChapterAudio,
  engineMode?: 'legacy_stems' | 'seed_scene',
): boolean => {
  // legacy_stems：保持旧完成条件，不引入 render_status 判定
  if (engineMode === 'legacy_stems') {
    const scriptStatus = String(chapterAudio.script_status || '').trim().toLowerCase()
    return Boolean(
      chapterAudio.has_script
      || chapterAudio.audio_path
      || scriptStatus === 'reviewed'
      || scriptStatus === 'approved'
    )
  }
  const renderStatus = String(chapterAudio.render_status || '').trim().toLowerCase()
  if (renderStatus) {
    return true
  }
  const scriptStatus = String(chapterAudio.script_status || '').trim().toLowerCase()
  return Boolean(
    chapterAudio.has_script
    || chapterAudio.audio_path
    || scriptStatus === 'reviewed'
    || scriptStatus === 'approved'
  )
}

export const resolveGeneratedChapterIdsFromProjects = (
  audiobookProjects: readonly { chapter_audios?: ChapterAudio[] | null }[],
  currentChapterAudios: readonly ChapterAudio[] = [],
  engineMode?: 'legacy_stems' | 'seed_scene',
): Set<number> => {
  const generatedChapterIds = new Set<number>()
  for (const chapterAudio of [
    ...audiobookProjects.flatMap((project) => project.chapter_audios || []),
    ...currentChapterAudios,
  ]) {
    if (isChapterGeneratedForEngine(chapterAudio, engineMode)) {
      generatedChapterIds.add(chapterAudio.chapter_id)
    }
  }
  return generatedChapterIds
}

const RENDER_LOCKED_STATUSES = new Set([
  'rendered_all_seed',
  'rendered_with_fallback',
  'stale',
])

const buildChapterRenderState = (
  chapterAudio: ChapterAudio,
  engineMode?: 'legacy_stems' | 'seed_scene',
  executionStatusByChapter?: Record<number, string | null> | null,
): ChapterRenderState | null => {
  if (engineMode === 'seed_scene') {
    const renderStatus = String(chapterAudio.render_status || '').trim().toLowerCase() || null
    const hasLegacyOutput = Boolean(
      chapterAudio.has_script
      || chapterAudio.audio_path
      || ['reviewed', 'approved'].includes(String(chapterAudio.script_status || '').trim().toLowerCase())
    )
    if (!renderStatus && !hasLegacyOutput) {
      return null
    }
    const exportable = Boolean(chapterAudio.audio_path)
    return {
      renderStatus,
      executionStatus: executionStatusByChapter?.[chapterAudio.chapter_id] ?? null,
      audioUrl: chapterAudio.audio_path || null,
      locked: Boolean(renderStatus && RENDER_LOCKED_STATUSES.has(renderStatus)),
      exportable,
    }
  }
  // legacy_stems：保持旧完成条件，不引入 render_status 判定
  if (!isChapterGeneratedForEngine(chapterAudio, 'legacy_stems')) {
    return null
  }
  return {
    renderStatus: null,
    executionStatus: executionStatusByChapter?.[chapterAudio.chapter_id] ?? null,
    audioUrl: chapterAudio.audio_path || null,
    locked: false,
    exportable: Boolean(chapterAudio.audio_path),
  }
}

/**
 * 章节渲染状态表（GUIDE §2.3/验收 9，R11/P2-1）：
 * 返回 chapterId -> ChapterRenderState；未生成章节不出现在结果中。
 * 多批次同章时按 engineMode 过滤后取优先级最高的状态（seed 投影 > legacy 完成态）。
 *
 * 引擎隔离：currentChapterAudios 来自当前批次，仅当其引擎
 * （currentBatchEngineMode，缺省 legacy_stems）与视图引擎一致时才计入；
 * 否则分轨产物会泄漏进场景生成视图，导致未生成章节被误锁。
 */
export const resolveChapterStateById = (
  audiobookProjects: readonly { id: number; engine_mode?: string | null; chapter_audios?: ChapterAudio[] | null }[],
  engineMode: 'legacy_stems' | 'seed_scene',
  currentChapterAudios: readonly ChapterAudio[] = [],
  executionStatusByChapter?: Record<number, string | null> | null,
  currentBatchEngineMode?: 'legacy_stems' | 'seed_scene' | string | null,
): Record<number, ChapterRenderState> => {
  const stateById: Record<number, ChapterRenderState> = {}
  const currentBatchEngine = (
    typeof currentBatchEngineMode === 'string' && currentBatchEngineMode.trim()
      ? currentBatchEngineMode
      : 'legacy_stems'
  ) === 'seed_scene' ? 'seed_scene' : 'legacy_stems'
  const candidateChapterAudios: ChapterAudio[] = [
    ...audiobookProjects
      .filter((project) => (project.engine_mode || 'legacy_stems') === engineMode)
      .flatMap((project) => project.chapter_audios || []),
    ...(currentBatchEngine === engineMode ? currentChapterAudios : []),
  ]
  for (const chapterAudio of candidateChapterAudios) {
    const state = buildChapterRenderState(chapterAudio, engineMode, executionStatusByChapter)
    if (!state) {
      continue
    }
    const existing = stateById[chapterAudio.chapter_id]
    // seed 投影优先；同优先级下保留先出现的（更早批次）
    if (!existing || (existing.renderStatus === null && state.renderStatus !== null)) {
      stateById[chapterAudio.chapter_id] = state
    }
  }
  return stateById
}

/**
 * 点击章节分流定位结果（GUIDE §2.5/阶段 3.1）。
 */
export interface ChapterBatchSelection {
  audiobookProjectId: number
  engineMode: 'legacy_stems' | 'seed_scene'
  renderStatus: string | null
}

/** 已发布产物锁定态（§2.5 规则 1：优先选择）。 */
const PUBLISHED_RENDER_STATUSES = new Set<string>([
  CHAPTER_RENDER_STATUS.RENDERED_ALL_SEED,
  CHAPTER_RENDER_STATUS.RENDERED_WITH_FALLBACK,
])

/** 按批次创建时间降序（缺失/非法时间退化为 id 降序），与历史入口排序一致。 */
const compareBatchByNewest = (
  a: { id: number; created_at?: string | null },
  b: { id: number; created_at?: string | null },
): number => {
  const ta = a.created_at ? Date.parse(a.created_at) : 0
  const tb = b.created_at ? Date.parse(b.created_at) : 0
  if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) return tb - ta
  return b.id - a.id
}

/**
 * 多批次选择规则（GUIDE §2.5，替换"取第一个"逻辑）：
 *
 * 1. 优先已发布产物的批次（render_status ∈ {rendered_all_seed, rendered_with_fallback}，
 *    按创建时间降序）；
 * 2. 其次最新创建批次；
 * 3. 编辑器内提供批次切换器（列表来自批次列表接口 engine_mode 过滤结果）。
 */
export const resolveAudiobookProjectForChapter = (
  audiobookProjects: readonly {
    id: number
    engine_mode?: string | null
    created_at?: string | null
    chapter_audios?: ChapterAudio[] | null
  }[],
  chapterId: number,
): ChapterBatchSelection | null => {
  const renderStatusOf = (audio: ChapterAudio): string | null => {
    const status = String(audio.render_status || '').trim().toLowerCase()
    return status || null
  }
  const candidates = audiobookProjects
    .map((project) => {
      const chapterAudio = project.chapter_audios?.find(
        (audio) => audio.chapter_id === chapterId,
      ) ?? null
      return { project, chapterAudio }
    })
    .filter((entry): entry is { project: typeof entry.project; chapterAudio: ChapterAudio } => (
      entry.chapterAudio !== null
    ))
  if (candidates.length === 0) {
    return null
  }
  const published = candidates
    .filter(({ chapterAudio }) => {
      const status = renderStatusOf(chapterAudio)
      return status !== null && PUBLISHED_RENDER_STATUSES.has(status)
    })
    .sort((a, b) => compareBatchByNewest(a.project, b.project))
  const best = published[0]
    ?? candidates.sort((a, b) => compareBatchByNewest(a.project, b.project))[0]
  return {
    audiobookProjectId: best.project.id,
    engineMode: best.project.engine_mode === 'seed_scene' ? 'seed_scene' : 'legacy_stems',
    renderStatus: renderStatusOf(best.chapterAudio),
  }
}

export const resolveAudiobookProjectIdForChapter = (
  audiobookProjects: readonly { id: number; chapter_audios?: ChapterAudio[] | null }[],
  chapterId: number,
): number | null => (
  resolveAudiobookProjectForChapter(audiobookProjects, chapterId)?.audiobookProjectId ?? null
)

export const normalizeSingleChapterSelection = ({
  chapters,
  selectedChapterIds,
  lockedChapterIds,
}: {
  chapters: readonly Chapter[]
  selectedChapterIds: readonly number[]
  lockedChapterIds: ReadonlySet<number>
}): number[] => {
  const availableChapterIds = new Set(
    chapters
      .filter((chapter) => !lockedChapterIds.has(chapter.id))
      .map((chapter) => chapter.id),
  )
  const selectedChapterId = selectedChapterIds.find((chapterId) => availableChapterIds.has(chapterId))
  if (selectedChapterId) {
    return [selectedChapterId]
  }
  const firstAvailableChapter = chapters.find((chapter) => availableChapterIds.has(chapter.id))
  return firstAvailableChapter ? [firstAvailableChapter.id] : []
}

export const toggleSingleChapterSelection = ({
  selectedChapterIds,
  chapterId,
  lockedChapterIds,
}: {
  selectedChapterIds: readonly number[]
  chapterId: number
  lockedChapterIds: ReadonlySet<number>
}): number[] => {
  const currentChapterId = selectedChapterIds[0]
  if (lockedChapterIds.has(chapterId)) {
    return currentChapterId ? [currentChapterId] : []
  }
  return [chapterId]
}
