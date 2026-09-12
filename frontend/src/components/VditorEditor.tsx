import { useEffect, useRef, useState } from 'react'
import Vditor from 'vditor'
import 'vditor/dist/index.css'
import { Box } from '@mui/material'
import { useTranslation } from 'react-i18next'

interface VditorEditorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  height?: number
}

export default function VditorEditor({
  value,
  onChange,
  placeholder,
  height = 500,
}: VditorEditorProps) {
  const { t } = useTranslation()
  const resolvedPlaceholder = placeholder ?? t('vditorEditor.placeholder')
  const vditorRef = useRef<Vditor | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [isReady, setIsReady] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return

    let vditor: Vditor | null = null
    let destroyed = false

    vditor = new Vditor(containerRef.current, {
      height,
      mode: 'ir', // 即时渲染模式 - 所见即所得
      placeholder: resolvedPlaceholder,
      value,
      // 使用本地资源，确保部署后不依赖外部 CDN
      cdn: '/vditor',
      cache: {
        enable: false, // 禁用本地缓存
      },
      toolbar: [
        'headings',
        'bold',
        'italic',
        'strike',
        '|',
        'list',
        'ordered-list',
        'check',
        '|',
        'quote',
        'code',
        'inline-code',
        '|',
        'undo',
        'redo',
        '|',
        'fullscreen',
      ],
      toolbarConfig: {
        pin: true,
      },
      input: (val: string) => {
        if (!destroyed) {
          onChange(val)
        }
      },
      after: () => {
        // 如果组件已卸载，不要继续
        if (destroyed) return
        // 编辑器初始化完成
        vditorRef.current = vditor
        setIsReady(true)
        // 设置初始值
        if (value && vditor) {
          vditor.setValue(value)
        }
      },
      // 中文界面
      lang: 'zh_CN',
      // 主题
      theme: 'classic',
      // 预览主题
      preview: {
        theme: {
          current: 'light',
        },
        hljs: {
          style: 'github',
        },
      },
    })

    return () => {
      destroyed = true
      setIsReady(false)
      // 安全销毁：检查 vditor 和其内部 element 是否存在
      if (vditor && vditorRef.current) {
        try {
          vditor.destroy()
        } catch (e) {
          // 忽略销毁时的错误
        }
      }
      vditorRef.current = null
    }
  }, [])

  // 当外部 value 变化时更新编辑器内容
  useEffect(() => {
    if (isReady && vditorRef.current) {
      const currentValue = vditorRef.current.getValue()
      if (value !== currentValue) {
        vditorRef.current.setValue(value)
      }
    }
  }, [value, isReady])

  return (
    <Box
      sx={{
        '& .vditor': {
          borderRadius: '8px',
          border: '1px solid',
          borderColor: 'grey.300',
        },
        '& .vditor-toolbar': {
          borderRadius: '8px 8px 0 0',
          bgcolor: 'grey.50',
        },
        '& .vditor-ir': {
          fontSize: '1rem',
          lineHeight: 1.8,
        },
        '& .vditor-ir pre.vditor-reset': {
          padding: '16px 24px',
        },
      }}
    >
      <div ref={containerRef} />
    </Box>
  )
}

