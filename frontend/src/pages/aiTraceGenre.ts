export const AI_TRACE_GENRES = ['通用', '玄幻', '都市', '言情', '悬疑', '科幻', '历史', '武侠'] as const

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
