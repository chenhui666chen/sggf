import {
  Box,
  Button,
  Chip,
  Typography,
} from '@mui/material'
import EditNoteIcon from '@mui/icons-material/EditNote'
import FactCheckIcon from '@mui/icons-material/FactCheck'

import { resolveScriptStatusPresentation } from './completionViewUtils'
import { audiobookButtonSx, audiobookColors } from './audiobookTheme'
import type { AudioEngineMode, Chapter, ChapterAudio } from './types'

interface ChapterScriptResultsProps {
  chapterAudios: ChapterAudio[]
  chapters: Chapter[]
  audiobookProjectId?: number
  /** GUIDE §2.5：按批次引擎分流审阅入口（seed_scene → 场景编辑器）。 */
  audioEngineMode?: AudioEngineMode
  onOpenScriptEditor: (chapterId: number) => void
  onOpenSceneEditor?: (chapterId: number) => void
  onOpenScriptReview?: (audiobookProjectId: number, chapterId: number) => void
}

const statusToneSx = {
  success: {
    color: audiobookColors.success,
    backgroundColor: audiobookColors.successSoft,
    borderColor: audiobookColors.successMain,
  },
  warning: {
    color: audiobookColors.warning,
    backgroundColor: audiobookColors.warningSoft,
    borderColor: audiobookColors.warningMain,
  },
  neutral: {
    color: audiobookColors.neutralText,
    backgroundColor: audiobookColors.neutralSoft,
    borderColor: audiobookColors.neutral,
  },
} as const

// 导出供单测：后端统计仅计 dialogue/narration，片段总数含 monologue，
// 此处按差值回填独白计数，避免出现 "48 片段 ≠ 14 对白 + 32 旁白" 的口径疑义
export const buildChapterScriptMetadata = (counts: {
  segment_count?: number | null
  dialogue_count?: number | null
  narration_count?: number | null
  character_count?: number | null
}): string[] => {
  const segmentCount = Math.max(0, Number(counts.segment_count) || 0)
  const dialogueCount = Math.max(0, Number(counts.dialogue_count) || 0)
  const narrationCount = Math.max(0, Number(counts.narration_count) || 0)
  const monologueCount = Math.max(0, segmentCount - dialogueCount - narrationCount)

  const metadata = [
    `${segmentCount} 个片段`,
    `${dialogueCount} 段对白`,
    `${narrationCount} 段旁白`,
  ]
  if (monologueCount > 0) {
    metadata.push(`${monologueCount} 段独白`)
  }
  if (counts.character_count) {
    metadata.push(`${Math.max(0, Number(counts.character_count) || 0)} 个角色`)
  }
  return metadata
}

const ChapterScriptResults = ({
  chapterAudios,
  chapters,
  audiobookProjectId,
  audioEngineMode,
  onOpenScriptEditor,
  onOpenSceneEditor,
  onOpenScriptReview,
}: ChapterScriptResultsProps) => {
  const scriptChapters = chapterAudios.filter((item) => Boolean(item.has_script))

  return (
    <Box component="section" sx={{ mt: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, mb: 1.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          章节剧本
        </Typography>
        <Chip size="small" label={`${scriptChapters.length} 章`} variant="outlined" />
      </Box>

      {scriptChapters.length === 0 ? (
        <Box
          sx={{
            py: 4,
            px: 2,
            textAlign: 'center',
            border: '1px dashed',
            borderColor: 'divider',
            borderRadius: 1,
          }}
        >
          <Typography variant="body2" color="text.secondary">
            暂无可审阅的章节剧本
          </Typography>
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {scriptChapters.map((chapterAudio) => {
            const chapter = chapters.find((item) => item.id === chapterAudio.chapter_id)
            const chapterNumber = chapter?.chapter_number ?? chapterAudio.chapter_number
            const chapterTitle = chapter?.title || `章节 ${chapterNumber || chapterAudio.chapter_id}`
            const status = resolveScriptStatusPresentation(chapterAudio.script_status)
            const canOpenReview = Boolean(
              chapterAudio.has_review && audiobookProjectId && onOpenScriptReview,
            )
            const metadata = buildChapterScriptMetadata(chapterAudio)

            return (
              <Box
                key={chapterAudio.id}
                sx={{
                  display: 'grid',
                  gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) auto' },
                  gap: 1.5,
                  alignItems: 'center',
                  p: { xs: 1.5, sm: 2 },
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                  backgroundColor: 'background.paper',
                }}
              >
                <Box sx={{ minWidth: 0 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 0.75 }}>
                    <Typography variant="body1" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>
                      {chapterNumber ? `第 ${chapterNumber} 章 · ${chapterTitle}` : chapterTitle}
                    </Typography>
                    <Chip
                      size="small"
                      variant="outlined"
                      label={status.label}
                      sx={{ ...statusToneSx[status.tone], height: 24 }}
                    />
                    {chapterAudio.has_review && (
                      <Chip size="small" variant="outlined" label="自动评审已完成" sx={{ height: 24 }} />
                    )}
                  </Box>
                  <Typography variant="caption" color="text.secondary">
                    {metadata.join(' · ')}
                  </Typography>
                </Box>

                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: { xs: 'flex-start', md: 'flex-end' } }}>
                  {canOpenReview && (
                    <Button
                      size="small"
                      variant="text"
                      startIcon={<FactCheckIcon />}
                      onClick={() => onOpenScriptReview?.(
                        audiobookProjectId as number,
                        chapterAudio.chapter_id,
                      )}
                    >
                      查看评审
                    </Button>
                  )}
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<EditNoteIcon />}
                    onClick={() => {
                      // GUIDE §2.5：seed_scene 章节走场景编辑器，避免落入 legacy 单片段工作台
                      if (audioEngineMode === 'seed_scene' && onOpenSceneEditor) {
                        onOpenSceneEditor(chapterAudio.chapter_id)
                        return
                      }
                      onOpenScriptEditor(chapterAudio.chapter_id)
                    }}
                    sx={audiobookButtonSx.brandOutlined}
                  >
                    {status.tone === 'success' ? '查看剧本' : '审阅并批准'}
                  </Button>
                </Box>
              </Box>
            )
          })}
        </Box>
      )}
    </Box>
  )
}

export default ChapterScriptResults
