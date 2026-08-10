/** 进化评审得分格式化：失败样本（如篇幅守门拦截）得分为 null，直接 toFixed 会崩溃白屏 */
export const formatScore = (value: number | null | undefined): string =>
  value == null ? '-' : value.toFixed(1)
