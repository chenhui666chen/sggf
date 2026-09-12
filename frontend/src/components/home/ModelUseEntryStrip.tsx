import { alpha, Box, ButtonBase, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

import type { AssetStudioTabId, ModelUseEntry } from './modelEntryData'

interface ModelUseEntryStripProps {
  activeEntryId: AssetStudioTabId
  entries: ModelUseEntry[]
  onSelect: (entryId: AssetStudioTabId) => void
}

export default function ModelUseEntryStrip({
  activeEntryId,
  entries,
  onSelect,
}: ModelUseEntryStripProps) {
  const { t } = useTranslation()
  return (
    <Box
      sx={{
        display: 'grid',
        gap: 1,
        gridTemplateColumns: {
          xs: 'repeat(2, minmax(0, 1fr))',
          sm: 'repeat(3, minmax(0, 1fr))',
          md: 'repeat(4, minmax(0, 1fr))',
          xl: `repeat(${entries.length}, minmax(0, 1fr))`,
        },
      }}
    >
      {entries.map((entry) => {
        const IconComponent = entry.icon
        const selected = entry.id === activeEntryId

        return (
          <ButtonBase
            key={entry.id}
            onClick={() => onSelect(entry.id)}
            sx={{
              borderRadius: 3,
              width: '100%',
              textAlign: 'left',
              justifyContent: 'flex-start',
              alignItems: 'stretch',
            }}
          >
            <Box
              sx={{
                width: '100%',
                minHeight: 74,
                borderRadius: 3,
                px: 1.25,
                py: 1.1,
                border: selected
                  ? `1px solid ${alpha(entry.color, 0.8)}`
                  : '1px solid rgba(255,255,255,0.12)',
                backgroundColor: selected ? alpha(entry.color, 0.18) : 'rgba(255,255,255,0.06)',
                boxShadow: selected ? `0 10px 24px ${alpha(entry.color, 0.18)}` : 'none',
                transition: 'all 0.25s ease',
                '&:hover': {
                  transform: 'translateY(-2px)',
                  borderColor: alpha(entry.color, 0.7),
                  backgroundColor: selected ? alpha(entry.color, 0.2) : 'rgba(255,255,255,0.1)',
                },
              }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Box
                  sx={{
                    width: 32,
                    height: 32,
                    borderRadius: 2,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backgroundColor: alpha(entry.color, 0.16),
                    color: entry.color,
                    flexShrink: 0,
                  }}
                >
                  <IconComponent sx={{ fontSize: 18 }} />
                </Box>
                <Box sx={{ minWidth: 0 }}>
                  <Typography
                    sx={{
                      color: 'white',
                      fontSize: '0.9rem',
                      fontWeight: 700,
                      lineHeight: 1.2,
                    }}
                  >
                    {t(entry.titleKey)}
                  </Typography>
                  <Typography
                    sx={{
                      color: 'rgba(255,255,255,0.68)',
                      fontSize: '0.72rem',
                      lineHeight: 1.25,
                      mt: 0.25,
                    }}
                  >
                    {t(entry.subtitleKey)}
                  </Typography>
                </Box>
              </Box>
            </Box>
          </ButtonBase>
        )
      })}
    </Box>
  )
}
