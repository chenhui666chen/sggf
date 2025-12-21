import { Box, Button, Card, CardContent, Chip, Container, Grid, Typography } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PlayCircleFilledWhiteIcon from '@mui/icons-material/PlayCircleFilledWhite'
import { useNavigate } from 'react-router-dom'

export default function DreamWeaverPage() {
  const navigate = useNavigate()

  return (
    <Box
      sx={{
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        py: 4,
      }}
    >
      <Container maxWidth="lg">
        <Button
          variant="text"
          startIcon={<ArrowBackIcon />}
          sx={{ color: 'white', mb: 2 }}
          onClick={() => navigate('/home')}
        >
          返回创作工坊
        </Button>

        <Typography variant="h4" sx={{ color: 'white', fontWeight: 700, mb: 1 }}>
          织梦映心 · 短剧创作
        </Typography>
        <Typography variant="body1" sx={{ color: 'rgba(255,255,255,0.85)', mb: 3 }}>
          当前接入模拟模型流程，可先跑通“首尾帧→视频→剪辑”链路；真实模型稍后灰度接入。
        </Typography>

        <Grid container spacing={2.5}>
          <Grid item xs={12} md={8}>
            <Card sx={{ borderRadius: 3, boxShadow: '0 12px 24px rgba(0,0,0,0.15)' }}>
              <CardContent>
                <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }}>
                  功能概览
                </Typography>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  · 分镜/首尾帧/中帧：使用模拟图片占位，验证数据契约与衔接逻辑
                </Typography>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  · 视频生成：由“织梦映心”模块调用 mock 视频适配器输出占位 MP4
                </Typography>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  · 剪辑合成：保持与真实流程一致，验证转场与文件落盘
                </Typography>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  · 后续计划：接入 Wan 2.6 R2v 与 next-scene LoRA，替换适配器即可
                </Typography>
                <Chip label="模拟线路已可用" color="primary" sx={{ mr: 1 }} />
                <Chip label="真实模型即将开放" variant="outlined" color="primary" />
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card sx={{ borderRadius: 3, textAlign: 'center', py: 3 }}>
              <CardContent>
                <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }}>
                  体验入口
                </Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                  立即跳转到 mock 流程，查看占位生成结果。
                </Typography>
                <Button
                  variant="contained"
                  startIcon={<PlayCircleFilledWhiteIcon />}
                  onClick={() => navigate('/drama/mock')}
                  sx={{ borderRadius: 2, px: 3 }}
                >
                  开始体验（Mock）
                </Button>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Container>
    </Box>
  )
}
