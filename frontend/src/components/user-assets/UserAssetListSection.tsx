import type { ReactNode } from 'react'

import {
  Alert,
  Box,
  Card,
  CardContent,
  CircularProgress,
  Grid,
  Pagination,
  Stack,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

import UserAssetBatchToolbar, {
  type UserAssetBatchToolbarProps,
} from './UserAssetBatchToolbar'
import UserAssetFilterToolbar, {
  type UserAssetFilterToolbarProps,
} from './UserAssetFilterToolbar'
import UserAssetLocalStoragePanel, {
  type UserAssetLocalStoragePanelProps,
} from './UserAssetLocalStoragePanel'
import type { UserAssetListStatusNotice } from './userAssetLocalDiagnosticsPresentation'

export type UserAssetListSectionProps = {
  filterToolbar: UserAssetFilterToolbarProps
  batchToolbar?: UserAssetBatchToolbarProps | null
  localStoragePanel?: UserAssetLocalStoragePanelProps | null
  statusNotices?: UserAssetListStatusNotice[] | null
  warningMessage?: string | null
  isLoading: boolean
  hasAssets: boolean
  hasFilteredAssets: boolean
  pagination?: {
    page: number
    totalPages: number
    totalItems: number
    pageSize: number
    currentPageCount: number
    disabled?: boolean
    onPageChange: (page: number) => void
  } | null
  emptyCollectionMessage: string
  emptyFilterMessage: string
  children: ReactNode
}

export default function UserAssetListSection(props: UserAssetListSectionProps) {
  const { t } = useTranslation()
  const {
    filterToolbar,
    batchToolbar,
    localStoragePanel,
    statusNotices,
    warningMessage,
    isLoading,
    hasAssets,
    hasFilteredAssets,
    pagination,
    emptyCollectionMessage,
    emptyFilterMessage,
    children,
  } = props

  return (
    <Stack spacing={3}>
      {statusNotices?.map((notice) => (
        <Alert key={`${notice.severity}:${notice.text}`} severity={notice.severity}>{notice.text}</Alert>
      ))}
      {warningMessage ? <Alert severity="warning">{warningMessage}</Alert> : null}
      {localStoragePanel ? <UserAssetLocalStoragePanel {...localStoragePanel} /> : null}

      <UserAssetFilterToolbar {...filterToolbar} />

      {hasFilteredAssets && batchToolbar ? <UserAssetBatchToolbar {...batchToolbar} /> : null}

      {isLoading ? (
        <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
          <CircularProgress />
        </Box>
      ) : !hasAssets ? (
        <Alert severity="info">{emptyCollectionMessage}</Alert>
      ) : !hasFilteredAssets ? (
        <Alert severity="info">{emptyFilterMessage}</Alert>
      ) : (
        <Stack spacing={2}>
          <Grid container spacing={2}>
            {children}
          </Grid>
          {pagination && pagination.totalItems > 0 ? (
            <Card variant="outlined" sx={{ borderRadius: 3 }}>
              <CardContent>
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    {t('userAsset.list.pagination', {
                      page: pagination.page,
                      totalPages: Math.max(pagination.totalPages, 1),
                      totalItems: pagination.totalItems,
                      currentPageCount: pagination.currentPageCount,
                      pageSize: pagination.pageSize,
                    })}
                  </Typography>
                  <Pagination
                    color="primary"
                    count={Math.max(pagination.totalPages, 1)}
                    page={Math.max(1, pagination.page)}
                    onChange={(_, page) => pagination.onPageChange(page)}
                    disabled={pagination.disabled || pagination.totalPages <= 1}
                  />
                </Stack>
              </CardContent>
            </Card>
          ) : null}
        </Stack>
      )}
    </Stack>
  )
}
