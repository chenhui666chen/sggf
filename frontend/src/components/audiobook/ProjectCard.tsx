import { MoreVert as MoreVertIcon } from '@mui/icons-material'
import { Box, Card, CardContent, Chip, IconButton, Typography } from '@mui/material'
import type { BookColors, Project } from '@/types/audiobook'

export default function ProjectCard({
  project,
  colors,
  onOpenProject,
  onOpenChapterDrawer,
}: {
  project: Project
  colors: BookColors
  onOpenProject: (project: Project) => void
  onOpenChapterDrawer: (project: Project) => void
}) {
  return (
    <Card
      sx={{
        cursor: 'pointer',
        transition: 'transform 0.25s ease, box-shadow 0.25s ease',
        background: 'linear-gradient(135deg, rgba(17,24,39,0.55) 0%, rgba(31,41,55,0.45) 100%)',
        border: '1px solid rgba(255,255,255,0.12)',
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 200,
        backdropFilter: 'blur(8px)',
        '&::before': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(circle at 20% 0%, ${colors.accent}26 0%, transparent 45%), radial-gradient(circle at 85% 85%, ${colors.secondary}22 0%, transparent 55%)`,
          pointerEvents: 'none',
        },
        '&:hover': {
          transform: 'translateY(-6px)',
          boxShadow: '0 16px 36px rgba(0,0,0,0.28)',
        },
        '&:hover .vinyl': { transform: 'rotate(10deg)' },
        '&:hover .vinyl .playOverlay': { opacity: 1 },
      }}
      onClick={() => onOpenProject(project)}
    >
      {/* 三点：快速打开“章节目录抽屉” */}
      <IconButton
        sx={{
          position: 'absolute',
          bottom: 8,
          right: 8,
          zIndex: 3,
        }}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation()
          onOpenChapterDrawer(project)
        }}
      >
        <MoreVertIcon />
      </IconButton>

      <CardContent
        sx={{
          width: '100%',
          position: 'relative',
          zIndex: 1,
          p: 2.5,
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 2,
            flexDirection: { xs: 'column', sm: 'row' },
          }}
        >
          {/* 封面 */}
          <Box
            sx={{
              width: { xs: '100%', sm: 150 },
              height: 170,
              borderRadius: 2,
              position: 'relative',
              overflow: 'hidden',
              boxShadow: '0 12px 26px rgba(0,0,0,0.35)',
              background: `linear-gradient(145deg, ${colors.primary} 0%, ${colors.secondary} 100%)`,
              flexShrink: 0,
              '&::before': {
                content: '""',
                position: 'absolute',
                inset: 0,
                background:
                  `radial-gradient(circle at 25% 25%, ${colors.accent}22 0%, transparent 55%), ` +
                  `repeating-linear-gradient(45deg, transparent, transparent 12px, ${colors.accent}10 12px, ${colors.accent}10 13px)`,
                opacity: 0.9,
                pointerEvents: 'none',
              },
              '&::after': {
                content: '""',
                position: 'absolute',
                inset: 10,
                border: `1px solid ${colors.accent}55`,
                borderRadius: 1.5,
                pointerEvents: 'none',
              },
            }}
          >
            <Box sx={{ position: 'absolute', top: 10, left: 10, zIndex: 1 }}>
              <Box
                sx={{
                  px: 1,
                  py: 0.25,
                  borderRadius: 999,
                  fontSize: '0.7rem',
                  fontWeight: 700,
                  letterSpacing: '1px',
                  color: 'rgba(255,255,255,0.9)',
                  backgroundColor: 'rgba(0,0,0,0.25)',
                  border: '1px solid rgba(255,255,255,0.18)',
                  display: 'inline-block',
                }}
              >
                AUDIOBOOK
              </Box>
            </Box>

            <Box
              sx={{
                position: 'relative',
                zIndex: 1,
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                px: 2,
                textAlign: 'center',
              }}
            >
              <Typography
                sx={{
                  fontFamily: '"STKaiti", "KaiTi", "楷体", serif',
                  color: colors.accent,
                  fontWeight: 800,
                  fontSize: '1.05rem',
                  textShadow: '0 2px 10px rgba(0,0,0,0.45)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  lineHeight: 1.25,
                  mb: 1,
                }}
              >
                {project.title}
              </Typography>

              <Box sx={{ display: 'flex', justifyContent: 'center' }}>
                <Chip
                  label={project.genre || '未分类'}
                  size="small"
                  sx={{
                    height: 22,
                    fontSize: '0.7rem',
                    color: 'rgba(255,255,255,0.9)',
                    borderColor: 'rgba(255,255,255,0.28)',
                    backgroundColor: 'rgba(0,0,0,0.18)',
                    border: '1px solid rgba(255,255,255,0.2)',
                  }}
                />
              </Box>
            </Box>
          </Box>

          {/* 唱片 */}
          <Box
            className="vinyl"
            sx={{
              width: 150,
              height: 150,
              borderRadius: '50%',
              position: 'relative',
              flexShrink: 0,
              backgroundImage:
                'radial-gradient(circle at 50% 50%, rgba(255,255,255,0.10) 0%, rgba(0,0,0,0.78) 38%, rgba(0,0,0,0.95) 72%),' +
                'repeating-radial-gradient(circle at 50% 50%, rgba(255,255,255,0.06) 0px, rgba(255,255,255,0.06) 1px, rgba(0,0,0,0) 2px, rgba(0,0,0,0) 6px)',
              boxShadow: '0 14px 28px rgba(0,0,0,0.35)',
              transform: 'rotate(-6deg)',
              transition: 'transform 0.25s ease',
              '&::before': {
                content: '""',
                position: 'absolute',
                inset: 6,
                borderRadius: '50%',
                border: `1px solid ${colors.accent}33`,
                pointerEvents: 'none',
              },
              '.vinylLabel': {
                position: 'absolute',
                inset: 46,
                borderRadius: '50%',
                background: `linear-gradient(145deg, ${colors.secondary} 0%, ${colors.primary} 100%)`,
                border: `1px solid ${colors.accent}55`,
                boxShadow: 'inset 0 0 0 4px rgba(0,0,0,0.25)',
              },
              '.vinylHole': {
                position: 'absolute',
                inset: 70,
                borderRadius: '50%',
                backgroundColor: 'rgba(0,0,0,0.65)',
                border: '1px solid rgba(255,255,255,0.12)',
              },
              '.playOverlay': {
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                opacity: 0,
                transition: 'opacity 0.2s ease',
              },
            }}
          >
            <Box className="vinylLabel" />
            <Box className="vinylHole" />
            <Box className="playOverlay">
              <Box
                sx={{
                  width: 52,
                  height: 52,
                  borderRadius: '50%',
                  backgroundColor: 'rgba(255,255,255,0.14)',
                  border: '1px solid rgba(255,255,255,0.25)',
                  backdropFilter: 'blur(6px)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Box
                  sx={{
                    width: 18,
                    height: 18,
                    backgroundColor: 'rgba(255,255,255,0.9)',
                    clipPath: 'polygon(28% 18%, 78% 50%, 28% 82%)',
                    transform: 'translateX(2px)',
                  }}
                />
              </Box>
            </Box>
          </Box>

          {/* 文案（移动端隐藏，避免拥挤） */}
          <Box sx={{ flex: 1, minWidth: 0, display: { xs: 'none', sm: 'block' } }}>
            <Typography
              sx={{
                color: 'rgba(255,255,255,0.92)',
                fontWeight: 800,
                fontSize: '0.98rem',
                mb: 0.5,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {project.title}
            </Typography>
            <Typography
              sx={{
                color: 'rgba(255,255,255,0.75)',
                fontSize: '0.8rem',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                lineHeight: 1.5,
              }}
            >
              {project.description || '点击进入有声生成与管理'}
            </Typography>
            <Box sx={{ mt: 1.25, display: 'flex', gap: 0.8, alignItems: 'flex-end' }}>
              {[10, 16, 12, 18, 11, 14, 9].map((h, idx) => (
                <Box
                  key={`wave-${idx}`}
                  sx={{
                    width: 6,
                    height: h,
                    borderRadius: 999,
                    background: `linear-gradient(180deg, ${colors.accent} 0%, rgba(255,255,255,0.08) 100%)`,
                    opacity: 0.85,
                  }}
                />
              ))}
            </Box>
          </Box>
        </Box>
      </CardContent>
    </Card>
  )
}

