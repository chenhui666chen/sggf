import type { ElementType } from 'react'
import type { SvgIconProps } from '@mui/material/SvgIcon'
import CenterFocusStrongOutlinedIcon from '@mui/icons-material/CenterFocusStrongOutlined'
import GraphicEqOutlinedIcon from '@mui/icons-material/GraphicEqOutlined'
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined'
import MovieCreationOutlinedIcon from '@mui/icons-material/MovieCreationOutlined'
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined'

export type AssetStudioTabId = 'image' | 'video' | 'motion' | 'audio' | 'vision-review'

export interface ModelUseEntry {
  id: AssetStudioTabId
  title: string
  subtitle: string
  description: string
  color: string
  icon: ElementType<SvgIconProps>
  status: 'ready' | 'planned'
}

export const modelUseEntries: ModelUseEntry[] = [
  {
    id: 'image',
    title: '图片生成',
    subtitle: '文生图 / 参考图生成',
    description: '直接填写提示词，或上传参考图后走图像编辑链路生成资产。',
    color: '#ff7b54',
    icon: ImageOutlinedIcon,
    status: 'ready',
  },
  {
    id: 'video',
    title: '视频生成',
    subtitle: '文生视频 / 图生视频',
    description: '支持纯提示词生成，也支持带首帧参考图的视频资产生成。',
    color: '#35b8a3',
    icon: MovieCreationOutlinedIcon,
    status: 'ready',
  },
  {
    id: 'motion',
    title: '动作控制',
    subtitle: '带参考图生成运动画面',
    description: '基于参考图和动作描述生成更偏控制型的视频资产。',
    color: '#4f8dfd',
    icon: CenterFocusStrongOutlinedIcon,
    status: 'ready',
  },
  {
    id: 'audio',
    title: '音乐音效',
    subtitle: '配乐 / 环境音 / 短音效',
    description: '统一走资产工作台音频入口，支持配乐和音效生成，不再混入模型中心导航。',
    color: '#ff9d2e',
    icon: GraphicEqOutlinedIcon,
    status: 'ready',
  },
  {
    id: 'vision-review',
    title: '视觉识别',
    subtitle: '图片 / 视频评价与改词',
    description: '调用具备视觉理解能力的模型识别素材质量，并给出评价和修改后的提示词。',
    color: '#f1b74a',
    icon: VisibilityOutlinedIcon,
    status: 'ready',
  },
]
