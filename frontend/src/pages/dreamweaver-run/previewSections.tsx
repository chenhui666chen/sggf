import type { ReactNode } from 'react'

import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  Typography,
} from '@mui/material'

import FormattedContent from '@/components/common/FormattedContent'
import type { DreamweaverAssetPlanItem, DreamweaverLibraryPlanItem } from '@/types/dreamweaver'

type DreamweaverRunAssetPreviewGridProps = {
  title: string
  uris: string[]
  kind: 'image' | 'video'
  previewsByUri: Record<string, string>
  loadingByUri: Record<string, boolean>
  errorsByUri: Record<string, string | null | undefined>
  canInteract: boolean
  onLoadPreview: (uri: string) => void
  onDownload: (uri: string) => void
  formatPath: (value: unknown) => string | null
}

function DreamweaverRunAssetPreviewCardMedia({
  previewUrl,
  kind,
}: {
  previewUrl: string
  kind: 'image' | 'video'
}) {
  if (!previewUrl) {
    return (
      <Box sx={{ mt: 0.75, bgcolor: '#fafafa', border: '1px dashed #ddd', borderRadius: 1, p: 1, textAlign: 'center' }}>
        <Typography variant="caption" color="text.secondary">
          未加载预览
        </Typography>
      </Box>
    )
  }

  if (kind === 'image') {
    return (
      <Box
        sx={{
          mt: 0.75,
          bgcolor: '#000',
          borderRadius: 1,
          overflow: 'hidden',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          p: 0.5,
        }}
      >
        <Box component="img" src={previewUrl} sx={{ maxWidth: '100%', maxHeight: 220, display: 'block', objectFit: 'contain' }} />
      </Box>
    )
  }

  return (
    <Box sx={{ mt: 0.75, bgcolor: '#000', borderRadius: 1, overflow: 'hidden' }}>
      <Box component="video" src={previewUrl} controls sx={{ width: '100%', maxHeight: 240, display: 'block' }} />
    </Box>
  )
}

function DreamweaverRunAssetPreviewCard({
  title,
  uri,
  kind,
  previewUrl,
  loading,
  error,
  canInteract,
  onLoadPreview,
  onDownload,
  formatPath,
}: {
  title: string
  uri: string
  kind: 'image' | 'video'
  previewUrl: string
  loading: boolean
  error?: string | null
  canInteract: boolean
  onLoadPreview: () => void
  onDownload: () => void
  formatPath: (value: unknown) => string | null
}) {
  const filename = uri.split(/[\\/]+/).pop() || uri
  const pathLabel = formatPath(uri)

  return (
    <Grid item xs={12} sm={6} md={4} key={`${title}:${uri}`}>
      <Card variant="outlined">
        <CardContent sx={{ p: 1.25 }}>
          <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
            {filename}
          </Typography>
          <DreamweaverRunAssetPreviewCardMedia previewUrl={previewUrl} kind={kind} />
          <Box sx={{ mt: 1, display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
            <Button size="small" variant="outlined" onClick={onLoadPreview} disabled={!canInteract || loading}>
              {loading ? '加载中…' : previewUrl ? '重新加载' : '加载预览'}
            </Button>
            <Button size="small" variant="text" onClick={onDownload} disabled={!canInteract || loading}>
              下载
            </Button>
            {pathLabel && <Chip size="small" label={pathLabel} variant="outlined" />}
          </Box>
          {error && (
            <Typography variant="caption" color="error" display="block" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
              {error}
            </Typography>
          )}
        </CardContent>
      </Card>
    </Grid>
  )
}

export function DreamweaverRunAssetPreviewGrid({
  title,
  uris,
  kind,
  previewsByUri,
  loadingByUri,
  errorsByUri,
  canInteract,
  onLoadPreview,
  onDownload,
  formatPath,
}: DreamweaverRunAssetPreviewGridProps) {
  const items = Array.from(new Set((uris || []).map((u) => String(u || '').trim()).filter(Boolean)))
  if (items.length === 0) return null

  return (
    <Box sx={{ mt: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
        {title}
      </Typography>
      <Grid container spacing={1}>
        {items.map((uri) => (
          <DreamweaverRunAssetPreviewCard
            key={`${title}:${uri}`}
            title={title}
            uri={uri}
            kind={kind}
            previewUrl={previewsByUri[uri] || ''}
            loading={Boolean(loadingByUri[uri])}
            error={errorsByUri[uri] || null}
            canInteract={canInteract}
            onLoadPreview={() => onLoadPreview(uri)}
            onDownload={() => onDownload(uri)}
            formatPath={formatPath}
          />
        ))}
      </Grid>
    </Box>
  )
}

type DreamweaverAssetPlanGridProps = {
  title: string
  items: DreamweaverAssetPlanItem[]
  previewsByUri: Record<string, string>
  loadingByUri: Record<string, boolean>
  errorsByUri: Record<string, string | null | undefined>
  canInteract: boolean
  onLoadPreview: (uri: string) => void
  onDownload: (uri: string) => void
  formatPath: (value: unknown) => string | null
}

export function DreamweaverAssetPlanGrid({
  title,
  items,
  previewsByUri,
  loadingByUri,
  errorsByUri,
  canInteract,
  onLoadPreview,
  onDownload,
  formatPath,
}: DreamweaverAssetPlanGridProps) {
  const list = Array.isArray(items) ? items : []
  if (!list.length) return null

  return (
    <Box sx={{ mt: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
        {title}
      </Typography>
      <Grid container spacing={1}>
        {list.map((item) => {
          const uri = item.uri ? String(item.uri).trim() : ''
          const previewUrl = uri ? previewsByUri[uri] || '' : ''
          const loading = uri ? Boolean(loadingByUri[uri]) : false
          const error = uri ? errorsByUri[uri] || null : null
          const status = item.status === 'done' || uri ? 'done' : item.status === 'processing' ? 'processing' : 'planned'
          const statusLabel = status === 'done' ? '已生成' : status === 'processing' ? '生成中' : '待生成'
          const statusColor: 'default' | 'success' | 'info' = status === 'done' ? 'success' : status === 'processing' ? 'info' : 'default'
          const label = String(item.label || item.id || '').trim() || item.id
          const kind = item.kind === 'video' ? 'video' : 'image'

          return (
            <Grid item xs={12} sm={6} md={4} key={`plan:${item.id}`}>
              <Card variant="outlined">
                <CardContent sx={{ p: 1.25 }}>
                  <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                      {label}
                    </Typography>
                    <Chip size="small" label={statusLabel} color={statusColor} />
                    {item.optional && <Chip size="small" label="可选" variant="outlined" />}
                  </Box>

                  {previewUrl ? (
                    <DreamweaverRunAssetPreviewCardMedia previewUrl={previewUrl} kind={kind} />
                  ) : (
                    <Box sx={{ mt: 0.75, bgcolor: '#fafafa', border: '1px dashed #ddd', borderRadius: 1, p: 1, textAlign: 'center' }}>
                      <Typography variant="caption" color="text.secondary">
                        {uri ? '已生成，待加载预览' : '生成中，等待素材'}
                      </Typography>
                    </Box>
                  )}

                  {uri && (
                    <Box sx={{ mt: 1, display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                      <Button size="small" variant="outlined" onClick={() => onLoadPreview(uri)} disabled={!canInteract || loading}>
                        {loading ? '加载中…' : previewUrl ? '重新加载' : '加载预览'}
                      </Button>
                      <Button size="small" variant="text" onClick={() => onDownload(uri)} disabled={!canInteract || loading}>
                        下载
                      </Button>
                      {formatPath(uri) && <Chip size="small" label={formatPath(uri)!} variant="outlined" />}
                    </Box>
                  )}

                  {(item.shot_id || item.scene_id) && (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                      {item.shot_id ? `Shot: ${item.shot_id}` : ''}
                      {item.scene_id ? `  Scene: ${item.scene_id}` : ''}
                    </Typography>
                  )}

                  {error && (
                    <Typography variant="caption" color="error" display="block" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
                      {error}
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>
          )
        })}
      </Grid>
    </Box>
  )
}

type DreamweaverStreamingPreviewProps = {
  step: number
  activeStreamKeys: string[]
  planText: string
  scriptText: string
  profileText: string
  audioText: string
  storyboardText: string
  cameraTreeText: string
  libraryPlanItems: DreamweaverLibraryPlanItem[]
  assetPlanItems: DreamweaverAssetPlanItem[]
  assetPlanSummary: {
    total: number
    done: number
    planned: number
    images: number
    videos: number
  }
  mergedVideoPlan: DreamweaverAssetPlanItem | null
  assetPlanGrid?: ReactNode
  mergedVideoPlanGrid?: ReactNode
}

function DreamweaverStreamingTextBlock({
  title,
  text,
  maxHeight = 220,
  monospace = false,
}: {
  title: string
  text: string
  maxHeight?: number
  monospace?: boolean
}) {
  if (!text) return null

  return (
    <Box sx={{ mb: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
        {title}
        <Box
          component="span"
          sx={{
            display: 'inline-block',
            width: 6,
            height: 14,
            bgcolor: 'primary.main',
            animation: 'blink 1s step-end infinite',
            verticalAlign: 'middle',
            ml: 0.5,
            borderRadius: 0.5,
            '@keyframes blink': {
              '50%': { opacity: 0 },
            },
          }}
        />
      </Typography>
      <Box sx={{ maxHeight, overflow: 'auto', bgcolor: '#fafafa', border: '1px solid #eee', borderRadius: 1, p: 1.5 }}>
        {monospace ? (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{
              whiteSpace: 'pre-wrap',
              fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
              fontSize: '0.85rem',
              lineHeight: 1.6,
            }}
          >
            {text}
          </Typography>
        ) : (
          <FormattedContent
            content={text}
            sx={{
              fontSize: '0.9rem',
              lineHeight: 1.7,
              '& p': { margin: '8px 0' },
              '& h1, & h2, & h3': { marginTop: '12px', marginBottom: '8px' },
            }}
          />
        )}
      </Box>
    </Box>
  )
}

function DreamweaverStreamingPreviewHeader({
  activeStreamKeys,
}: {
  activeStreamKeys: string[]
}) {
  return (
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        流式预览
      </Typography>
      {activeStreamKeys.length > 0 && <Chip size="small" label={`实时输出: ${activeStreamKeys.join(', ')}`} />}
    </Box>
  )
}

function DreamweaverStreamingLibraryPlanCard({
  item,
}: {
  item: DreamweaverLibraryPlanItem
}) {
  const statusLabel = item.status === 'done' ? '已生成' : item.status === 'processing' ? '生成中...' : '待生成'
  const label = item.label || item.entity_name || item.role

  return (
    <Grid item key={item.id} xs={6} sm={4} md={3} lg={2}>
      <Card
        sx={{
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          border: item.status === 'processing' ? '2px solid' : '1px solid',
          borderColor: item.status === 'processing' ? 'warning.main' : 'divider',
          opacity: item.status === 'planned' ? 0.7 : 1,
        }}
      >
        <Box
          sx={{
            position: 'relative',
            paddingTop: '100%',
            bgcolor: 'grey.100',
            overflow: 'hidden',
          }}
        >
          {item.status === 'processing' ? (
            <Box
              sx={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                textAlign: 'center',
              }}
            >
              <Box
                sx={{
                  width: 24,
                  height: 24,
                  border: '2px solid',
                  borderColor: 'primary.main',
                  borderTopColor: 'transparent',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                  '@keyframes spin': {
                    '0%': { transform: 'rotate(0deg)' },
                    '100%': { transform: 'rotate(360deg)' },
                  },
                }}
              />
            </Box>
          ) : (
            <Box
              sx={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                textAlign: 'center',
              }}
            >
              <PhotoCameraIcon sx={{ fontSize: 32, color: 'grey.400' }} />
            </Box>
          )}
          {(item.status === 'processing' || item.status === 'done') && (
            <Box
              sx={{
                position: 'absolute',
                top: 4,
                right: 4,
                bgcolor: item.status === 'processing' ? 'warning.main' : 'success.main',
                color: 'white',
                fontSize: '0.65rem',
                px: 0.5,
                py: 0.25,
                borderRadius: 0.5,
              }}
            >
              {item.status === 'processing' ? '生成中' : '完成'}
            </Box>
          )}
        </Box>
        <CardContent sx={{ p: 1, '&:last-child': { pb: 1 } }}>
          <Typography variant="caption" sx={{ fontWeight: 500, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {label}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
            {statusLabel}
          </Typography>
        </CardContent>
      </Card>
    </Grid>
  )
}

export function DreamweaverStreamingPreview({
  step,
  activeStreamKeys,
  planText,
  scriptText,
  profileText,
  audioText,
  storyboardText,
  cameraTreeText,
  libraryPlanItems,
  assetPlanItems,
  assetPlanSummary,
  mergedVideoPlan,
  assetPlanGrid,
  mergedVideoPlanGrid,
}: DreamweaverStreamingPreviewProps) {
  if (step === 0) {
    if (!planText && !scriptText && !profileText && !audioText) return null
    return (
      <Box sx={{ mb: 1 }}>
        <DreamweaverStreamingPreviewHeader activeStreamKeys={activeStreamKeys} />
        <DreamweaverStreamingTextBlock title="计划/脚本提要（流式）" text={planText} maxHeight={200} />
        <DreamweaverStreamingTextBlock title="剧本（流式）" text={scriptText} maxHeight={400} />
        <DreamweaverStreamingTextBlock title="角色小传（流式）" text={profileText} maxHeight={200} />
        <DreamweaverStreamingTextBlock title="音频标记（流式）" text={audioText} maxHeight={200} monospace />
      </Box>
    )
  }

  if (step === 1) {
    if (!storyboardText && !cameraTreeText) return null
    return (
      <Box sx={{ mb: 1 }}>
        <DreamweaverStreamingPreviewHeader activeStreamKeys={activeStreamKeys} />
        <DreamweaverStreamingTextBlock title="分镜（流式）" text={storyboardText} maxHeight={400} />
        <DreamweaverStreamingTextBlock title="镜头树（流式）" text={cameraTreeText} maxHeight={260} />
      </Box>
    )
  }

  if (step === 2) {
    if (!libraryPlanItems.length) return null
    const plannedCount = libraryPlanItems.filter((item) => item.status === 'planned').length
    const doneCount = libraryPlanItems.filter((item) => item.status === 'done').length
    const processingCount = libraryPlanItems.filter((item) => item.status === 'processing').length

    return (
      <Box sx={{ mb: 1 }}>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            素材库生成
          </Typography>
          <Chip size="small" label={`总计: ${libraryPlanItems.length}`} />
          <Chip size="small" label={`已生成: ${doneCount}`} color={doneCount > 0 ? 'success' : 'default'} />
          <Chip size="small" label={`生成中: ${processingCount}`} color={processingCount > 0 ? 'warning' : 'default'} />
          <Chip size="small" label={`待生成: ${plannedCount}`} />
        </Box>
        <Grid container spacing={1.5}>
          {libraryPlanItems.slice(0, 12).map((item) => (
            <DreamweaverStreamingLibraryPlanCard key={item.id} item={item} />
          ))}
          {libraryPlanItems.length > 12 && (
            <Grid item xs={12}>
              <Typography variant="caption" color="text.secondary">
                还有 {libraryPlanItems.length - 12} 个素材...
              </Typography>
            </Grid>
          )}
        </Grid>
      </Box>
    )
  }

  if (step === 3) {
    const assets = assetPlanItems.filter((item) => item.id !== 'merged_video')
    if (!assets.length) return null

    return (
      <Box sx={{ mb: 1 }}>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 0.5 }}>
          <Chip size="small" label={`占位: ${assetPlanSummary.total}`} />
          <Chip size="small" label={`已生成: ${assetPlanSummary.done}`} color={assetPlanSummary.done > 0 ? 'success' : 'default'} />
          <Chip size="small" label={`待生成: ${assetPlanSummary.planned}`} />
          <Chip size="small" label={`图像: ${assetPlanSummary.images}`} />
          <Chip size="small" label={`视频: ${assetPlanSummary.videos}`} />
        </Box>
        {assetPlanGrid ?? null}
      </Box>
    )
  }

  if (step === 4) {
    if (!mergedVideoPlan) return null

    return (
      <Box sx={{ mb: 1 }}>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            流式预览
          </Typography>
          <Chip size="small" label={mergedVideoPlan.uri ? '已生成' : '待生成'} color={mergedVideoPlan.uri ? 'success' : 'default'} />
        </Box>
        {mergedVideoPlanGrid ?? null}
      </Box>
    )
  }

  return null
}

type DreamweaverScriptStageSnapshotViewProps = {
  planText: string
  scriptText: string
  scriptApproved: boolean
  characterProfiles: unknown[]
  audioMarkers: unknown[]
  scriptEntities: unknown
  scriptGeneration: unknown
  entitySummary: string
}

export function DreamweaverScriptStageSnapshotView({
  planText,
  scriptText,
  scriptApproved,
  characterProfiles,
  audioMarkers,
  scriptEntities,
  scriptGeneration,
  entitySummary,
}: DreamweaverScriptStageSnapshotViewProps) {
  const profilesCount = characterProfiles.length
  const markersCount = audioMarkers.length
  const hasGeneration = Boolean(scriptGeneration && typeof scriptGeneration === 'object' && Object.keys(scriptGeneration as object).length > 0)

  const renderSnapshotMonospaceBox = (content: string, maxHeight = 240) => (
    <Box
      sx={{
        whiteSpace: 'pre-wrap',
        fontFamily: 'monospace',
        fontSize: 12,
        bgcolor: '#fafafa',
        border: '1px solid #eee',
        borderRadius: 2,
        p: 1.5,
        maxHeight,
        overflow: 'auto',
      }}
    >
      {content}
    </Box>
  )

  const renderJsonBlock = (value: unknown, emptyText: string, maxHeight = 240) => {
    const isEmpty =
      value == null ||
      (Array.isArray(value) ? value.length === 0 : typeof value === 'object' && Object.keys(value).length === 0)
    if (isEmpty) {
      return (
        <Typography variant="body2" color="text.secondary">
          {emptyText}
        </Typography>
      )
    }
    return renderSnapshotMonospaceBox(JSON.stringify(value, null, 2), maxHeight)
  }

  const renderHeader = (title: string, extra?: ReactNode) => (
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        {title}
      </Typography>
      {extra ?? null}
    </Box>
  )

  const renderJsonAccordion = (title: string, value: unknown, emptyText: string, extra?: ReactNode) => (
    <Accordion>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>{renderHeader(title, extra)}</AccordionSummary>
      <AccordionDetails>{renderJsonBlock(value, emptyText)}</AccordionDetails>
    </Accordion>
  )

  const renderTextAccordion = ({
    title,
    text,
    emptyText,
    defaultExpanded = false,
    extra,
  }: {
    title: string
    text: string
    emptyText: string
    defaultExpanded?: boolean
    extra?: ReactNode
  }) => (
    <Accordion defaultExpanded={defaultExpanded}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>{renderHeader(title, extra)}</AccordionSummary>
      <AccordionDetails>
        <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
          {text || emptyText}
        </Typography>
      </AccordionDetails>
    </Accordion>
  )

  return (
    <Box sx={{ mb: 1 }}>
      {renderTextAccordion({
        title: '计划 / 剧本提要（快照）',
        text: planText,
        emptyText: '暂无计划/提要快照（可能仍在生成或尚未落库）。',
        defaultExpanded: true,
      })}

      <Accordion defaultExpanded>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          {renderHeader(
            '剧本（快照）',
            <>
              <Chip size="small" label={scriptApproved ? '已通过' : '未通过'} color={scriptApproved ? 'success' : 'default'} />
              <Chip size="small" label={`长度: ${scriptText.length}`} />
            </>,
          )}
        </AccordionSummary>
        <AccordionDetails>
          {scriptText ? (
            renderSnapshotMonospaceBox(scriptText.length > 6000 ? `${scriptText.slice(0, 6000)}\n…` : scriptText, 320)
          ) : (
            <Typography variant="body2" color="text.secondary">
              尚无可用剧本快照（可能仍在生成或尚未落库）。
            </Typography>
          )}
        </AccordionDetails>
      </Accordion>

      {renderJsonAccordion(
        '角色小传（快照）',
        characterProfiles,
        '暂无角色小传（可能尚未生成或未落库）。',
        profilesCount > 0 ? <Chip size="small" label={`${profilesCount} 条`} /> : null,
      )}

      {renderJsonAccordion(
        '音频标记（快照）',
        audioMarkers,
        '暂无音频标记（可能尚未生成或未落库）。',
        markersCount > 0 ? <Chip size="small" label={`${markersCount} 条`} /> : null,
      )}

      {renderJsonAccordion(
        '实体抽取（快照）',
        scriptEntities,
        '暂无实体抽取数据（可能尚未生成或未落库）。',
        entitySummary ? <Chip size="small" label={entitySummary} /> : null,
      )}

      {renderJsonAccordion(
        '剧本生成信息（快照）',
        scriptGeneration,
        '暂无剧本生成信息（可能尚未生成或未落库）。',
        hasGeneration ? <Chip size="small" label="已记录" /> : null,
      )}
    </Box>
  )
}
