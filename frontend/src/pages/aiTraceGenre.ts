export const AI_TRACE_GENRES = ['通用', '玄幻', '都市', '言情', '悬疑', '科幻', '历史', '武侠'] as const

// 显示层标签 i18n key 映射：值本身是提交后端的协议值，不可翻译，仅展示时经 labelKey 取翻译。
export type AITraceGenreValue = (typeof AI_TRACE_GENRES)[number] | '其他'

export const AI_TRACE_GENRE_LABEL_KEYS: Record<AITraceGenreValue, string> = {
  通用: 'aiTrace.genre.general',
  玄幻: 'aiTrace.genre.fantasy',
  都市: 'aiTrace.genre.urban',
  言情: 'aiTrace.genre.romance',
  悬疑: 'aiTrace.genre.mystery',
  科幻: 'aiTrace.genre.scifi',
  历史: 'aiTrace.genre.history',
  武侠: 'aiTrace.genre.wuxia',
  其他: 'aiTrace.genre.others',
}

// 样本系统 genre 选项：AI_TRACE_GENRES 去掉「通用」+ 补充「其他」（prompt-evolution 样本协议值）
export const AI_TRACE_SAMPLE_GENRES: readonly AITraceGenreValue[] = [
  '玄幻', '都市', '言情', '悬疑', '科幻', '历史', '武侠', '其他',
] as const

const GENRE_ALIASES: Record<string, (typeof AI_TRACE_GENRES)[number]> = {
  general: '通用', 通用: '通用',
  fantasy: '玄幻', 玄幻: '玄幻', 玄幻小说: '玄幻',
  urban: '都市', 都市: '都市', 都市小说: '都市',
  romance: '言情', 言情: '言情', 言情小说: '言情',
  mystery: '悬疑', suspense: '悬疑', 悬疑: '悬疑',
  'sci-fi': '科幻', scifi: '科幻', 'science fiction': '科幻', 科幻: '科幻',
  history: '历史', historical: '历史', 历史: '历史',
  wuxia: '武侠', 武侠: '武侠', 武侠小说: '武侠',
}

export function normalizeAITraceGenre(genre: unknown): string {
  if (typeof genre !== 'string' || !genre.trim()) return 'auto'
  return GENRE_ALIASES[genre.trim().toLowerCase()] ?? 'auto'
}
