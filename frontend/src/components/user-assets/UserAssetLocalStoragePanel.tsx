import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  Stack,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'

import type { LocalAssetExternalDirectoryStatus } from '@/utils/localAssetExternalDirectory'
import { downloadTextFile } from '@/utils/fileDownload'

import {
  buildUserAssetLocalStorageBackupGuide,
  buildUserAssetLocalStorageBackupGuideFilename,
  type UserAssetLocalStorageActionReport,
  type UserAssetLocalStorageActionIssueItem,
  buildUserAssetLocalStorageActionIssueTypeLabel,
  countUserAssetLocalStorageRebuildCandidates,
  buildUserAssetLocalStoragePanelCopy,
  buildUserAssetLocalStorageSupportLabel,
  buildUserAssetRecordedDirectoryLabel,
} from './userAssetLocalStoragePanelPresentation'
import type { UserAssetExternalDirectoryAssetHealthSummary } from './userAssetLocalDiagnosticsPresentation'

export type UserAssetLocalStoragePanelProps = {
  status: LocalAssetExternalDirectoryStatus | null
  healthSummary?: UserAssetExternalDirectoryAssetHealthSummary | null
  submittingLabel?: string | null
  lastActionReport?: UserAssetLocalStorageActionReport | null
  loading: boolean
  submitting: boolean
  onRefresh: () => void
  onExportLocalAssetInventory: () => void
  onExportLocalAssetRebuildList: () => void
  onRestoreMissingLocalCopies: () => void
  onRestoreIssueItem: (item: UserAssetLocalStorageActionIssueItem) => void
  onNavigateToIssueSource?: ((path: string) => void) | null
  onPreviewFilteredMissingLocalCopies: () => void
  onRestoreFilteredMissingLocalCopies: () => void
  onPickDirectory: () => void
  onRecoverAccess: () => void
  onClearDirectory: () => void
}

function buildActionIssueLocationLabel(item: UserAssetLocalStorageActionIssueItem): string {
  const externalRelativePath = String(item.externalRelativePath || '').trim()
  if (externalRelativePath) {
    return `目录相对路径：${externalRelativePath}`
  }

  const localStoragePath = String(item.localStoragePath || '').trim()
  if (localStoragePath) {
    return `本地存储路径：${localStoragePath}`
  }

  return '登记路径：未记录'
}

function buildActionIssueGroupTitle(
  report: UserAssetLocalStorageActionReport,
  issueType: UserAssetLocalStorageActionIssueItem['issueType'],
  count: number,
): string {
  if (issueType === 'directory_inaccessible') {
    return `目录异常明细（${count}）`
  }

  return report.mode === 'preview'
    ? `可重建的缺失副本（${count}）`
    : `本次扫描命中的缺失副本（${count}）`
}

function buildActionIssueGroupDescription(
  report: UserAssetLocalStorageActionReport,
  issueType: UserAssetLocalStorageActionIssueItem['issueType'],
): string {
  if (issueType === 'directory_inaccessible') {
    return '这些资产当前受目录权限或目录可达性影响，需要先恢复访问后再校验或补录。'
  }

  return report.mode === 'preview'
    ? '这些资产在当前筛选下缺少本地副本，可先查看范围与路径，再决定是否执行重建。'
    : '这些资产是启动重建前扫描到的缺失副本；实际恢复结果以上方摘要为准。'
}

export default function UserAssetLocalStoragePanel(props: UserAssetLocalStoragePanelProps) {
  const {
    status,
    healthSummary = null,
    submittingLabel = null,
    lastActionReport = null,
    loading,
    submitting,
    onRefresh,
    onExportLocalAssetInventory,
    onExportLocalAssetRebuildList,
    onRestoreMissingLocalCopies,
    onRestoreIssueItem,
    onNavigateToIssueSource = null,
    onPreviewFilteredMissingLocalCopies,
    onRestoreFilteredMissingLocalCopies,
    onPickDirectory,
    onRecoverAccess,
    onClearDirectory,
  } = props

  const panelCopy = buildUserAssetLocalStoragePanelCopy(status, loading)
  const busy = loading || submitting
  const supportLabel = buildUserAssetLocalStorageSupportLabel(status, loading)
  const recordedDirectoryLabel = buildUserAssetRecordedDirectoryLabel(status, loading)
  const rebuildCandidateCount = countUserAssetLocalStorageRebuildCandidates(healthSummary)
  const missingLocalCopyCount = Math.max(0, healthSummary?.missingLocalCopyCount || 0)
  const inaccessibleAssetCount = Math.max(0, healthSummary?.inaccessibleAssetCount || 0)
  const missingIssueItems = (lastActionReport?.issueItems || [])
    .filter((item) => item.issueType === 'missing_local_copy')
  const inaccessibleIssueItems = (lastActionReport?.issueItems || [])
    .filter((item) => item.issueType === 'directory_inaccessible')

  const handleExportBackupGuide = () => {
    const generatedAt = new Date()
    downloadTextFile({
      content: buildUserAssetLocalStorageBackupGuide({
        status,
        loading,
        generatedAt,
      }),
      filename: buildUserAssetLocalStorageBackupGuideFilename(generatedAt),
      mimeType: 'text/markdown',
    })
  }

  return (
    <Card variant="outlined" sx={{ borderRadius: 3, borderColor: 'rgba(15, 23, 42, 0.08)' }}>
      <CardContent>
        <Stack spacing={1.5}>
          <Stack spacing={0.5}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              用户目录存储
            </Typography>
            <Typography variant="body2" color="text.secondary">
              这里管理 File System Access API 目录句柄。当前仅 Asset Studio 与 Audiobook 页面中的显式“收录”会优先写入用户目录，播放器试听缓存等自动路径仍保留在浏览器管理的本地存储中。
            </Typography>
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
            <Chip
              size="small"
              color={panelCopy.statusTone}
              label={`状态：${panelCopy.statusLabel}`}
            />
            <Chip
              size="small"
              variant="outlined"
              label={`浏览器：${supportLabel}`}
            />
          </Stack>

          <Alert severity={panelCopy.severity}>{panelCopy.summary}</Alert>

          {submittingLabel ? (
            <Alert severity="info">{submittingLabel}</Alert>
          ) : null}

          <Stack
            spacing={0.75}
            sx={{
              px: 1.25,
              py: 1,
              borderRadius: 2,
              border: '1px solid rgba(15, 23, 42, 0.08)',
              backgroundColor: 'rgba(15, 23, 42, 0.02)',
            }}
          >
            <Typography variant="body2">
              已记录目录：{recordedDirectoryLabel}
            </Typography>
            <Typography variant="body2">
              当前优先入口：Asset Studio 显式收录、Audiobook 手动收录
            </Typography>
            <Typography variant="body2">
              仍走浏览器存储：播放器试听缓存等自动本地缓存
            </Typography>
            <Typography variant="body2" color="text.secondary">
              待重建清单：{rebuildCandidateCount > 0
                ? `当前有 ${rebuildCandidateCount} 项待处理记录，可导出重建清单后逐项补录。`
                : '当前没有待导出的重建项。'}
            </Typography>
            {missingLocalCopyCount > 0 ? (
              <Typography variant="body2" color="text.secondary">
                当前页缺失副本：检测到 {missingLocalCopyCount} 项可尝试直接重新收录到本地。
              </Typography>
            ) : null}
            {inaccessibleAssetCount > 0 ? (
              <Typography variant="body2" color="text.secondary">
                当前页目录异常：有 {inaccessibleAssetCount} 项登记为用户目录副本，需先恢复目录访问后再校验或重建。
              </Typography>
            ) : null}
            <Typography variant="body2" color="text.secondary">
              跨页重建：可按当前筛选条件补扫全部分页结果，并尝试重建其中缺失的本地副本。
            </Typography>
            {panelCopy.guidance ? (
              <Typography variant="body2" color="text.secondary">
                恢复建议：{panelCopy.guidance}
              </Typography>
            ) : null}
            {panelCopy.backupHint ? (
              <Typography variant="body2" color="text.secondary">
                备份建议：{panelCopy.backupHint}
              </Typography>
            ) : null}
          </Stack>

          {lastActionReport ? (
            <Stack
              spacing={1}
              sx={{
                px: 1.25,
                py: 1,
                borderRadius: 2,
                border: '1px solid rgba(15, 23, 42, 0.08)',
                backgroundColor: 'rgba(15, 23, 42, 0.02)',
              }}
            >
              <Alert severity={lastActionReport.severity}>
                <Stack spacing={0.5}>
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                    {lastActionReport.title}
                  </Typography>
                  <Typography variant="body2">
                    {lastActionReport.summary}
                  </Typography>
                  <Typography variant="caption">
                    完成时间：{lastActionReport.completedAtLabel}
                  </Typography>
                </Stack>
              </Alert>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
                {lastActionReport.metrics.map((metric) => (
                  <Chip
                    key={metric.key}
                    size="small"
                    variant="outlined"
                    label={`${metric.label}：${metric.value}`}
                  />
                ))}
              </Stack>
              {lastActionReport.issueItems.length > 0 ? (
                <Stack spacing={1}>
                  <Typography variant="body2" color="text.secondary">
                    {lastActionReport.mode === 'preview'
                      ? '本次预览命中的问题资产如下，可展开查看明细后再决定是否执行重建。'
                      : '以下为本次扫描命中的问题资产明细，便于回看处理范围与后续补录。'}
                  </Typography>
                  {missingIssueItems.length > 0 ? (
                    <Accordion
                      defaultExpanded
                      disableGutters
                      sx={{
                        borderRadius: 2,
                        border: '1px solid rgba(15, 23, 42, 0.08)',
                        backgroundColor: 'transparent',
                        '&::before': { display: 'none' },
                      }}
                    >
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Stack spacing={0.25}>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>
                            {buildActionIssueGroupTitle(lastActionReport, 'missing_local_copy', missingIssueItems.length)}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {buildActionIssueGroupDescription(lastActionReport, 'missing_local_copy')}
                          </Typography>
                        </Stack>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Stack spacing={1}>
                          {missingIssueItems.map((item) => (
                            <Stack
                              key={item.key}
                              spacing={0.4}
                              sx={{
                                py: 0.75,
                                '&:not(:last-of-type)': {
                                  borderBottom: '1px solid rgba(15, 23, 42, 0.08)',
                                },
                              }}
                            >
                              <Stack
                                direction={{ xs: 'column', sm: 'row' }}
                                spacing={0.75}
                                useFlexGap
                                flexWrap="wrap"
                                alignItems={{ xs: 'flex-start', sm: 'center' }}
                              >
                                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                  {item.title}
                                </Typography>
                                <Chip
                                  size="small"
                                  variant="outlined"
                                  label={`来源：${item.sourceModule}`}
                                />
                              </Stack>
                              <Typography variant="caption" color="text.secondary">
                                问题类型：{buildUserAssetLocalStorageActionIssueTypeLabel(item.issueType)}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                资产 UUID：{item.assetUuid}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {buildActionIssueLocationLabel(item)}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                处理建议：{item.actionHint}
                              </Typography>
                              {item.sourceActionPath || (item.issueType === 'missing_local_copy' && item.restorableAsset) ? (
                                <Stack direction="row" spacing={1} sx={{ pt: 0.25 }}>
                                  {item.sourceActionPath ? (
                                    <Button
                                      size="small"
                                      variant="text"
                                      onClick={() => onNavigateToIssueSource?.(item.sourceActionPath || '/user-center')}
                                      disabled={busy || !onNavigateToIssueSource}
                                    >
                                      {item.sourceActionLabel || '查看来源'}
                                    </Button>
                                  ) : null}
                                  {item.issueType === 'missing_local_copy' && item.restorableAsset ? (
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      onClick={() => onRestoreIssueItem(item)}
                                      disabled={busy}
                                    >
                                      重新收录到本地
                                    </Button>
                                  ) : null}
                                </Stack>
                              ) : null}
                            </Stack>
                          ))}
                        </Stack>
                      </AccordionDetails>
                    </Accordion>
                  ) : null}
                  {inaccessibleIssueItems.length > 0 ? (
                    <Accordion
                      defaultExpanded
                      disableGutters
                      sx={{
                        borderRadius: 2,
                        border: '1px solid rgba(15, 23, 42, 0.08)',
                        backgroundColor: 'transparent',
                        '&::before': { display: 'none' },
                      }}
                    >
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Stack spacing={0.25}>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>
                            {buildActionIssueGroupTitle(lastActionReport, 'directory_inaccessible', inaccessibleIssueItems.length)}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {buildActionIssueGroupDescription(lastActionReport, 'directory_inaccessible')}
                          </Typography>
                        </Stack>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Stack spacing={1}>
                          {inaccessibleIssueItems.map((item) => (
                            <Stack
                              key={item.key}
                              spacing={0.4}
                              sx={{
                                py: 0.75,
                                '&:not(:last-of-type)': {
                                  borderBottom: '1px solid rgba(15, 23, 42, 0.08)',
                                },
                              }}
                            >
                              <Stack
                                direction={{ xs: 'column', sm: 'row' }}
                                spacing={0.75}
                                useFlexGap
                                flexWrap="wrap"
                                alignItems={{ xs: 'flex-start', sm: 'center' }}
                              >
                                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                  {item.title}
                                </Typography>
                                <Chip
                                  size="small"
                                  variant="outlined"
                                  label={`来源：${item.sourceModule}`}
                                />
                              </Stack>
                              <Typography variant="caption" color="text.secondary">
                                问题类型：{buildUserAssetLocalStorageActionIssueTypeLabel(item.issueType)}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                资产 UUID：{item.assetUuid}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {buildActionIssueLocationLabel(item)}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                处理建议：{item.actionHint}
                              </Typography>
                              {item.sourceActionPath ? (
                                <Stack direction="row" spacing={1} sx={{ pt: 0.25 }}>
                                  <Button
                                    size="small"
                                    variant="text"
                                    onClick={() => onNavigateToIssueSource?.(item.sourceActionPath || '/user-center')}
                                    disabled={busy || !onNavigateToIssueSource}
                                  >
                                    {item.sourceActionLabel || '查看来源'}
                                  </Button>
                                </Stack>
                              ) : null}
                            </Stack>
                          ))}
                        </Stack>
                      </AccordionDetails>
                    </Accordion>
                  ) : null}
                </Stack>
              ) : null}
            </Stack>
          ) : null}

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} flexWrap="wrap">
            <Button
              variant="contained"
              onClick={onPickDirectory}
              disabled={busy || !status?.supported}
            >
              {submitting ? '处理中...' : panelCopy.pickLabel}
            </Button>
            {panelCopy.showRecoverAccess ? (
              <Button
                variant="outlined"
                onClick={onRecoverAccess}
                disabled={busy || !status?.supported}
              >
                恢复访问
              </Button>
            ) : null}
            <Button
              variant="outlined"
              onClick={onClearDirectory}
              disabled={busy || !panelCopy.clearEnabled}
            >
              清除目录配置
            </Button>
            <Button
              variant="outlined"
              onClick={onExportLocalAssetInventory}
              disabled={busy}
            >
              导出本地资产清单
            </Button>
            <Button
              variant="outlined"
              onClick={onRestoreMissingLocalCopies}
              disabled={busy || missingLocalCopyCount <= 0}
            >
              重建当前页缺失副本
            </Button>
            <Button
              variant="outlined"
              onClick={onPreviewFilteredMissingLocalCopies}
              disabled={busy}
            >
              扫描当前筛选（预览）
            </Button>
            <Button
              variant="outlined"
              onClick={onRestoreFilteredMissingLocalCopies}
              disabled={busy}
            >
              扫描当前筛选并重建
            </Button>
            <Button
              variant="outlined"
              onClick={onExportLocalAssetRebuildList}
              disabled={busy || rebuildCandidateCount <= 0}
            >
              导出重建清单
            </Button>
            <Button
              variant="outlined"
              onClick={handleExportBackupGuide}
              disabled={busy}
            >
              导出备份说明
            </Button>
            <Button
              variant="text"
              onClick={onRefresh}
              disabled={busy}
            >
              刷新状态
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  )
}
