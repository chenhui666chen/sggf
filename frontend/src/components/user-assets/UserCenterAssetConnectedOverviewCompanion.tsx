import type { ReactElement, ReactNode } from 'react'

import {
  Box,
  Chip,
  Stack,
  Typography,
} from '@mui/material'

export type UserCenterAssetConnectedOverviewCompanionSummaryItem = {
  label: string
  value: ReactNode
}

export type UserCenterAssetConnectedOverviewStrategyCompanionContentOptions = {
  items: string[]
}

export type UserCenterAssetConnectedOverviewPointsRulesCompanionContentValue = {
  sourceLabel: string
  sourceColor: 'default' | 'primary'
  updatedAtLabel: string
  description: string
  summaryItems: UserCenterAssetConnectedOverviewCompanionSummaryItem[]
  updatedByLabel: string
}

export type UserCenterAssetConnectedOverviewPointsRulesCompanionContentOptions = {
  content: UserCenterAssetConnectedOverviewPointsRulesCompanionContentValue | null
  emptyText: string
}

export function buildUserCenterAssetConnectedOverviewStrategyCompanionContent(
  options: UserCenterAssetConnectedOverviewStrategyCompanionContentOptions,
): ReactElement {
  return <UserCenterAssetConnectedOverviewStrategyCompanionContent {...options} />
}

export function buildUserCenterAssetConnectedOverviewPointsRulesCompanionContent(
  options: UserCenterAssetConnectedOverviewPointsRulesCompanionContentOptions,
): ReactElement {
  return <UserCenterAssetConnectedOverviewPointsRulesCompanionContent {...options} />
}

export function UserCenterAssetConnectedOverviewStrategyCompanionContent(
  props: UserCenterAssetConnectedOverviewStrategyCompanionContentOptions,
) {
  return (
    <Stack spacing={1.25} sx={{ mt: 2 }}>
      {props.items.map((item, index) => (
        <Typography key={`${index + 1}-${item}`} variant="body2" color="text.secondary">
          {index + 1}. {item}
        </Typography>
      ))}
    </Stack>
  )
}

export function UserCenterAssetConnectedOverviewPointsRulesCompanionContent(
  props: UserCenterAssetConnectedOverviewPointsRulesCompanionContentOptions,
) {
  if (!props.content) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
        {props.emptyText}
      </Typography>
    )
  }

  const {
    description,
    sourceColor,
    sourceLabel,
    summaryItems,
    updatedAtLabel,
    updatedByLabel,
  } = props.content

  return (
    <Stack spacing={1.5} sx={{ mt: 2 }}>
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
        <Chip size="small" color={sourceColor} label={sourceLabel} />
        <Chip size="small" variant="outlined" label={updatedAtLabel} />
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {description}
      </Typography>
      <UserCenterAssetConnectedOverviewCompanionSummaryGrid items={summaryItems} />
      <Typography variant="caption" color="text.secondary">
        {updatedByLabel}
      </Typography>
    </Stack>
  )
}

type UserCenterAssetConnectedOverviewCompanionSummaryGridProps = {
  items: UserCenterAssetConnectedOverviewCompanionSummaryItem[]
}

function UserCenterAssetConnectedOverviewCompanionSummaryGrid(
  props: UserCenterAssetConnectedOverviewCompanionSummaryGridProps,
) {
  return (
    <Box sx={{ display: 'grid', gap: 1.25, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
      {props.items.map((item) => (
        <Box
          key={item.label}
          sx={{ p: 1.5, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2 }}
        >
          <Typography variant="caption" color="text.secondary">
            {item.label}
          </Typography>
          <Typography sx={{ mt: 0.5, fontWeight: 600 }}>{item.value}</Typography>
        </Box>
      ))}
    </Box>
  )
}
