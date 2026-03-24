export function getStoryExpansionSummary(result: any): { label: string; text: string } | null {
  const legacySummary = typeof result?.story_expansion_analysis?.analysis_summary === 'string'
    ? result.story_expansion_analysis.analysis_summary.trim()
    : ''
  if (legacySummary) {
    return { label: '协同建议', text: legacySummary }
  }

  const coordinationSummary = typeof result?.coordination_summary === 'string'
    ? result.coordination_summary.trim()
    : ''
  if (coordinationSummary) {
    return { label: '协同摘要', text: coordinationSummary }
  }

  const analysisSummary = typeof result?.expansion_analysis?.analysis_summary === 'string'
    ? result.expansion_analysis.analysis_summary.trim()
    : ''
  if (analysisSummary) {
    return { label: '协同摘要', text: analysisSummary }
  }

  return null
}


export function buildStoryExpansionCompletionMessage(baseMessage: string, result: any): string {
  const summary = getStoryExpansionSummary(result)
  if (!summary) {
    return baseMessage
  }

  return `${baseMessage} ${summary.label}：${summary.text}`
}
