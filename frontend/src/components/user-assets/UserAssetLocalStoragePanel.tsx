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
import { useTranslation } from 'react-i18next'

import { useAppLanguage } from '@/i18n'
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

function buildActionIssueLocationLabel(item: UserAssetLocalStorageActionIssueItem, t: (key: string, options?: Record<string, unknown>) => string): string {
  const externalRelativePath = String(item.externalRelativePath || '').trim()
  if (externalRelativePath) {
    return t('userAsset.localStorage.issueExternalRelativePath', { path: externalRelativePath })
  }

  const localStoragePath = String(item.localStoragePath || '').trim()
  if (localStoragePath) {
    return t('userAsset.localStorage.issueLocalStoragePath', { path: localStoragePath })
  }

  return t('userAsset.localStorage.issueNoRecordedPath')
}

function buildActionIssueGroupTitle(
  report: UserAssetLocalStorageActionReport,
  issueType: UserAssetLocalStorageActionIssueItem['issueType'],
  count: number,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (issueType === 'directory_inaccessible') {
    return t('userAsset.localStorage.groupDirectoryDetail', { count })
  }

  return report.mode === 'preview'
    ? t('userAsset.localStorage.groupRebuildableMissing', { count })
    : t('userAsset.localStorage.groupScannedMissing', { count })
}

function buildActionIssueGroupDescription(
  report: UserAssetLocalStorageActionReport,
  issueType: UserAssetLocalStorageActionIssueItem['issueType'],
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (issueType === 'directory_inaccessible') {
    return t('userAsset.localStorage.groupDirectoryDescription')
  }

  return report.mode === 'preview'
    ? t('userAsset.localStorage.groupPreviewDescription')
    : t('userAsset.localStorage.groupRestoreDescription')
}

export default function UserAssetLocalStoragePanel(props: UserAssetLocalStoragePanelProps) {
  const { t } = useTranslation()
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

  // 备份说明是一份导出的 Markdown，里面的时间跟着当前界面语言走。
  const { language } = useAppLanguage()

  const panelCopy = buildUserAssetLocalStoragePanelCopy(status, loading, t)
  const busy = loading || submitting
  const supportLabel = buildUserAssetLocalStorageSupportLabel(status, loading, t)
  const recordedDirectoryLabel = buildUserAssetRecordedDirectoryLabel(status, loading, t)
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
        locale: language,
      }),
      filename: buildUserAssetLocalStorageBackupGuideFilename(generatedAt),
      mimeType: 'text/markdown',
    })
  }

  return (
    <Card variant="outlined" sx={{ borderRadius: 3, borderColor: 'divider' }}>
      <CardContent>
        <Stack spacing={1.5}>
          <Stack spacing={0.5}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              {t('userAsset.localStorage.panelTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t('userAsset.localStorage.panelDescription')}
            </Typography>
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
            <Chip
              size="small"
              color={panelCopy.statusTone}
              label={t('userAsset.localStorage.statusPrefix', { status: panelCopy.statusLabel })}
            />
            <Chip
              size="small"
              variant="outlined"
              label={t('userAsset.localStorage.browserPrefix', { support: supportLabel })}
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
              border: '1px solid',
              borderColor: 'divider',
              backgroundColor: 'grey.100',
            }}
          >
            <Typography variant="body2">
              {t('userAsset.localStorage.recordedDirectory', { directory: recordedDirectoryLabel })}
            </Typography>
            <Typography variant="body2">
              {t('userAsset.localStorage.priorityEntry')}
            </Typography>
            <Typography variant="body2">
              {t('userAsset.localStorage.browserStorageNote')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {rebuildCandidateCount > 0
                ? t('userAsset.localStorage.rebuildListCount', { count: rebuildCandidateCount })
                : t('userAsset.localStorage.rebuildListEmpty')}
            </Typography>
            {missingLocalCopyCount > 0 ? (
              <Typography variant="body2" color="text.secondary">
                {t('userAsset.localStorage.currentPageMissing', { count: missingLocalCopyCount })}
              </Typography>
            ) : null}
            {inaccessibleAssetCount > 0 ? (
              <Typography variant="body2" color="text.secondary">
                {t('userAsset.localStorage.currentPageInaccessible', { count: inaccessibleAssetCount })}
              </Typography>
            ) : null}
            <Typography variant="body2" color="text.secondary">
              {t('userAsset.localStorage.crossPageRebuild')}
            </Typography>
            {panelCopy.guidance ? (
              <Typography variant="body2" color="text.secondary">
                {t('userAsset.localStorage.recoveryAdvice', { advice: panelCopy.guidance })}
              </Typography>
            ) : null}
            {panelCopy.backupHint ? (
              <Typography variant="body2" color="text.secondary">
                {t('userAsset.localStorage.backupAdvice', { advice: panelCopy.backupHint })}
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
                border: '1px solid',
                borderColor: 'divider',
                backgroundColor: 'grey.100',
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
                    {t('userAsset.localStorage.completedAt', { time: lastActionReport.completedAtLabel })}
                  </Typography>
                </Stack>
              </Alert>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
                {lastActionReport.metrics.map((metric) => (
                  <Chip
                    key={metric.key}
                    size="small"
                    variant="outlined"
                    label={t('userAsset.localStorage.metricLine', { label: metric.label, value: metric.value })}
                  />
                ))}
              </Stack>
              {lastActionReport.issueItems.length > 0 ? (
                <Stack spacing={1}>
                  <Typography variant="body2" color="text.secondary">
                    {lastActionReport.mode === 'preview'
                      ? t('userAsset.localStorage.issuePreviewNote')
                      : t('userAsset.localStorage.issueRestoreNote')}
                  </Typography>
                  {missingIssueItems.length > 0 ? (
                    <Accordion
                      defaultExpanded
                      disableGutters
                      sx={{
                        borderRadius: 2,
                        border: '1px solid',
                        borderColor: 'divider',
                        backgroundColor: 'transparent',
                        '&::before': { display: 'none' },
                      }}
                    >
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Stack spacing={0.25}>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>
                            {buildActionIssueGroupTitle(lastActionReport, 'missing_local_copy', missingIssueItems.length, t)}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {buildActionIssueGroupDescription(lastActionReport, 'missing_local_copy', t)}
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
                                  borderBottom: '1px solid',
                                  borderBottomColor: 'divider',
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
                                  label={t('userAsset.localStorage.issueSource', { source: item.sourceModule })}
                                />
                              </Stack>
                              <Typography variant="caption" color="text.secondary">
                                {t('userAsset.localStorage.issueType', { type: buildUserAssetLocalStorageActionIssueTypeLabel(item.issueType, t) })}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {t('userAsset.localStorage.issueUuid', { uuid: item.assetUuid })}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {buildActionIssueLocationLabel(item, t)}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {t('userAsset.localStorage.issueActionHint', { hint: item.actionHint })}
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
                                      {item.sourceActionLabel || t('userAsset.common.viewSource')}
                                    </Button>
                                  ) : null}
                                  {item.issueType === 'missing_local_copy' && item.restorableAsset ? (
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      onClick={() => onRestoreIssueItem(item)}
                                      disabled={busy}
                                    >
                                      {t('userAsset.card.restoreLocal')}
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
                        border: '1px solid',
                        borderColor: 'divider',
                        backgroundColor: 'transparent',
                        '&::before': { display: 'none' },
                      }}
                    >
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Stack spacing={0.25}>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>
                            {buildActionIssueGroupTitle(lastActionReport, 'directory_inaccessible', inaccessibleIssueItems.length, t)}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {buildActionIssueGroupDescription(lastActionReport, 'directory_inaccessible', t)}
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
                                  borderBottom: '1px solid',
                                  borderBottomColor: 'divider',
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
                                  label={t('userAsset.localStorage.issueSource', { source: item.sourceModule })}
                                />
                              </Stack>
                              <Typography variant="caption" color="text.secondary">
                                {t('userAsset.localStorage.issueType', { type: buildUserAssetLocalStorageActionIssueTypeLabel(item.issueType, t) })}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {t('userAsset.localStorage.issueUuid', { uuid: item.assetUuid })}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {buildActionIssueLocationLabel(item, t)}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {t('userAsset.localStorage.issueActionHint', { hint: item.actionHint })}
                              </Typography>
                              {item.sourceActionPath ? (
                                <Stack direction="row" spacing={1} sx={{ pt: 0.25 }}>
                                  <Button
                                    size="small"
                                    variant="text"
                                    onClick={() => onNavigateToIssueSource?.(item.sourceActionPath || '/user-center')}
                                    disabled={busy || !onNavigateToIssueSource}
                                  >
                                    {item.sourceActionLabel || t('userAsset.common.viewSource')}
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
              {submitting ? t('userAsset.common.processingShort') : panelCopy.pickLabel}
            </Button>
            {panelCopy.showRecoverAccess ? (
              <Button
                variant="outlined"
                onClick={onRecoverAccess}
                disabled={busy || !status?.supported}
              >
                {t('userAsset.localStorage.recoverAccess')}
              </Button>
            ) : null}
            <Button
              variant="outlined"
              onClick={onClearDirectory}
              disabled={busy || !panelCopy.clearEnabled}
            >
              {t('userAsset.localStorage.clearDirectory')}
            </Button>
            <Button
              variant="outlined"
              onClick={onExportLocalAssetInventory}
              disabled={busy}
            >
              {t('userAsset.localStorage.exportInventory')}
            </Button>
            <Button
              variant="outlined"
              onClick={onRestoreMissingLocalCopies}
              disabled={busy || missingLocalCopyCount <= 0}
            >
              {t('userAsset.localStorage.rebuildCurrentPage')}
            </Button>
            <Button
              variant="outlined"
              onClick={onPreviewFilteredMissingLocalCopies}
              disabled={busy}
            >
              {t('userAsset.localStorage.scanPreview')}
            </Button>
            <Button
              variant="outlined"
              onClick={onRestoreFilteredMissingLocalCopies}
              disabled={busy}
            >
              {t('userAsset.localStorage.scanAndRebuild')}
            </Button>
            <Button
              variant="outlined"
              onClick={onExportLocalAssetRebuildList}
              disabled={busy || rebuildCandidateCount <= 0}
            >
              {t('userAsset.localStorage.exportRebuildList')}
            </Button>
            <Button
              variant="outlined"
              onClick={handleExportBackupGuide}
              disabled={busy}
            >
              {t('userAsset.localStorage.exportBackupGuide')}
            </Button>
            <Button
              variant="text"
              onClick={onRefresh}
              disabled={busy}
            >
              {t('userAsset.localStorage.refreshStatus')}
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  )
}
