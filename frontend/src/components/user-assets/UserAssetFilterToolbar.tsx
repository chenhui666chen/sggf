import RefreshIcon from '@mui/icons-material/Refresh'
import {
  Button,
  Card,
  CardContent,
  Chip,
  MenuItem,
  Stack,
  TextField,
} from '@mui/material'

import type {
  UserAssetListArchiveFilter,
  UserAssetListFilters,
  UserAssetListViewFilter,
  UserAssetSourceOption,
} from './userAssetListPresentation'
import {
  buildUserAssetFilterToolbarPresentation,
  isUserAssetArchiveFilter,
  isUserAssetViewFilter,
} from './userAssetFilterToolbarPresentation'

export type UserAssetFilterToolbarProps = {
  filters: Pick<
    UserAssetListFilters,
    'viewFilter' | 'kindFilter' | 'sourceFilter' | 'archiveFilter' | 'tagFilter'
  >
  kindOptions: string[]
  sourceOptions: UserAssetSourceOption[]
  tagOptions: string[]
  filteredCount: number
  loading?: boolean
  onViewFilterChange: (value: UserAssetListViewFilter) => void
  onKindFilterChange: (value: string) => void
  onSourceFilterChange: (value: string) => void
  onArchiveFilterChange: (value: UserAssetListArchiveFilter) => void
  onTagFilterChange: (value: string) => void
  onRefresh: () => void
}

export default function UserAssetFilterToolbar(props: UserAssetFilterToolbarProps) {
  const {
    filters,
    kindOptions,
    sourceOptions,
    tagOptions,
    filteredCount,
    loading = false,
    onViewFilterChange,
    onKindFilterChange,
    onSourceFilterChange,
    onArchiveFilterChange,
    onTagFilterChange,
    onRefresh,
  } = props

  const presentation = buildUserAssetFilterToolbarPresentation({
    filters,
    kindOptions,
    sourceOptions,
    tagOptions,
    filteredCount,
    loading,
  })

  const handleFieldChange = (fieldKey: string, value: string) => {
    switch (fieldKey) {
      case 'viewFilter':
        if (isUserAssetViewFilter(value)) onViewFilterChange(value)
        return
      case 'kindFilter':
        onKindFilterChange(value)
        return
      case 'sourceFilter':
        onSourceFilterChange(value)
        return
      case 'archiveFilter':
        if (isUserAssetArchiveFilter(value)) onArchiveFilterChange(value)
        return
      case 'tagFilter':
        onTagFilterChange(value)
        return
      default:
        return
    }
  }

  return (
    <Card variant="outlined" sx={{ borderRadius: 3 }}>
      <CardContent>
        <Stack direction={{ xs: 'column', lg: 'row' }} spacing={1.5} justifyContent="space-between">
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} flexWrap="wrap">
            {presentation.fields.map((field) => (
              <TextField
                key={field.key}
                select
                size="small"
                label={field.label}
                value={field.value}
                onChange={(event) => handleFieldChange(field.key, event.target.value)}
                sx={{ minWidth: { xs: '100%', sm: 180 } }}
              >
                {field.options.map((option) => (
                  <MenuItem key={`${field.key}-${option.value}`} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
            ))}
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'stretch', sm: 'center' }}>
            <Chip size="small" color="primary" variant="outlined" label={presentation.resultLabel} />
            <Button
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={onRefresh}
              disabled={presentation.refreshDisabled}
            >
              {presentation.refreshLabel}
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  )
}
