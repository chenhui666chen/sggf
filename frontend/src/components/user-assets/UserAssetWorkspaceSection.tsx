import type { ReactNode } from 'react'

import { Stack } from '@mui/material'

import UserAssetEditorDialog, {
  type UserAssetEditorDialogProps,
} from './UserAssetEditorDialog'
import UserAssetListSection, {
  type UserAssetListSectionProps,
} from './UserAssetListSection'
import UserAssetOverviewMetrics from './UserAssetOverviewMetrics'
import type { UserAssetOverviewMetricSpec } from './userAssetOverviewPresentation'

export type UserAssetWorkspaceSectionProps = {
  overviewMetrics: UserAssetOverviewMetricSpec[]
  listSection: Omit<UserAssetListSectionProps, 'children'>
  editorDialog: UserAssetEditorDialogProps
  children: ReactNode
}

export default function UserAssetWorkspaceSection(props: UserAssetWorkspaceSectionProps) {
  const {
    overviewMetrics,
    listSection,
    editorDialog,
    children,
  } = props

  return (
    <Stack spacing={2.5}>
      <UserAssetOverviewMetrics metrics={overviewMetrics} />
      <UserAssetListSection {...listSection}>{children}</UserAssetListSection>
      <UserAssetEditorDialog {...editorDialog} />
    </Stack>
  )
}
