import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CloseIcon from '@mui/icons-material/Close'
import PlaylistAddCheckIcon from '@mui/icons-material/PlaylistAddCheck'

import { apiClient } from '../../services/api'
import { audiobookColors } from './audiobookTheme'

interface SfxCandidateReviewDialogProps {
  open: boolean
  onClose: () => void
}

interface SfxCandidate {
  source: string
  source_id: string
  name: string
  description: string
  source_url: string
  license: string
  license_url: string
  license_commercial: boolean
  attribution_required: boolean
  author: string
  duration: number
  tags: string[]
  status: string
}

type ReviewStatus = 'approved' | 'rejected' | 'needs_info'

interface ReviewDraft {
  review_status: ReviewStatus
  license_verified: boolean
  local_file: string
  category: string
  style: string
}

const DEFAULT_REVIEW: ReviewDraft = {
  review_status: 'needs_info',
  license_verified: false,
  local_file: '',
  category: '',
  style: '',
}

const SFX_CATEGORIES = ['environment', 'action', 'emotion', 'transition']
const SFX_STYLES = ['realistic', 'cinematic', 'fantasy', 'scifi', 'horror', 'peaceful', 'intense']

const reviewKey = (candidate: Pick<SfxCandidate, 'source' | 'source_id'>) =>
  `${candidate.source}:${candidate.source_id}`

const SfxCandidateReviewDialog = ({ open, onClose }: SfxCandidateReviewDialogProps) => {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [candidates, setCandidates] = useState<SfxCandidate[]>([])
  const [reviews, setReviews] = useState<Record<string, ReviewDraft>>({})
  const [sourceDir, setSourceDir] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const approvedCount = useMemo(
    () => Object.values(reviews).filter((item) => item.review_status === 'approved').length,
    [reviews],
  )

  const loadCandidates = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.listSfxCandidates()
      setCandidates(res.data.items)
      setReviews((prev) => {
        const next = { ...prev }
        res.data.items.forEach((item) => {
          const key = reviewKey(item)
          if (!next[key]) next[key] = { ...DEFAULT_REVIEW }
        })
        return next
      })
    } catch {
      setError(t('audiobook.sfxCandidateReview.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    loadCandidates()
  }, [open, loadCandidates])

  const updateReview = (candidate: SfxCandidate, patch: Partial<ReviewDraft>) => {
    const key = reviewKey(candidate)
    setReviews((prev) => ({
      ...prev,
      [key]: {
        ...(prev[key] || DEFAULT_REVIEW),
        ...patch,
      },
    }))
  }

  const handleBuildManifest = async () => {
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const items = candidates.map((candidate) => {
        const review = reviews[reviewKey(candidate)] || DEFAULT_REVIEW
        return {
          source: candidate.source,
          source_id: candidate.source_id,
          review_status: review.review_status,
          license_verified: review.license_verified,
          local_file: review.local_file,
          category: review.category,
          style: review.style,
        }
      })
      const res = await apiClient.buildSfxCandidateManifestDraft({
        source_dir: sourceDir || undefined,
        items,
      })
      setMessage(t('audiobook.sfxCandidateReview.manifestGenerated', {
        path: res.data.manifest_path,
      }))
    } catch {
      setError(t('audiobook.sfxCandidateReview.buildFailed'))
    } finally {
      setSaving(false)
    }
  }

  const handleClose = () => {
    setMessage('')
    setError('')
    onClose()
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        {t('audiobook.sfxCandidateReview.title')}
        <IconButton onClick={handleClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Alert severity="info" sx={{ mb: 2 }}>
          {t('audiobook.sfxCandidateReview.infoHint')}
        </Alert>

        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          <TextField
            size="small"
            label={t('audiobook.sfxCandidateReview.sourceDirLabel')}
            placeholder={t('audiobook.sfxCandidateReview.sourceDirPlaceholder')}
            value={sourceDir}
            onChange={(event) => setSourceDir(event.target.value)}
            sx={{ flex: 1 }}
          />
          <Button
            size="small"
            variant="outlined"
            onClick={loadCandidates}
            disabled={loading}
          >
            {t('audiobook.sfxCandidateReview.refresh')}
          </Button>
        </Box>

        {message && <Alert severity="success" sx={{ mb: 2 }}>{message}</Alert>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : candidates.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
            {t('audiobook.sfxCandidateReview.noCandidates')}
          </Typography>
        ) : (
          <List dense disablePadding sx={{ maxHeight: 520, overflow: 'auto' }}>
            {candidates.map((candidate) => {
              const draft = reviews[reviewKey(candidate)] || DEFAULT_REVIEW
              return (
                <ListItem
                  key={reviewKey(candidate)}
                  alignItems="flex-start"
                  sx={{ borderBottom: '1px solid', borderColor: 'divider', px: 0, py: 1.5 }}
                >
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center', flexWrap: 'wrap' }}>
                        <Typography variant="subtitle2">{candidate.name}</Typography>
                        <Chip label={candidate.source} size="small" variant="outlined" />
                        <Chip
                          label={candidate.license || t('audiobook.sfxCandidateReview.unknownLicense')}
                          size="small"
                          color={candidate.license_commercial ? 'success' : 'warning'}
                        />
                        {candidate.attribution_required && <Chip label={t('audiobook.sfxCandidateReview.attributionChip')} size="small" />}
                      </Box>
                    }
                    secondary={
                      <Box sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary">
                          {candidate.description || candidate.source_url || t('audiobook.sfxCandidateReview.noDescription')}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 0.5, mt: 1, flexWrap: 'wrap' }}>
                          {candidate.tags.slice(0, 4).map((tag) => (
                            <Chip key={tag} label={tag} size="small" sx={{ backgroundColor: audiobookColors.brandFaint }} />
                          ))}
                          {candidate.duration > 0 && <Chip label={`${candidate.duration.toFixed(1)}s`} size="small" />}
                          {candidate.author && <Chip label={candidate.author} size="small" variant="outlined" />}
                        </Box>
                        <Box sx={{ display: 'grid', gridTemplateColumns: '150px 1fr 130px 130px', gap: 1, mt: 1.5 }}>
                          <FormControl size="small">
                            <InputLabel>{t('audiobook.sfxCandidateReview.reviewLabel')}</InputLabel>
                            <Select
                              label={t('audiobook.sfxCandidateReview.reviewLabel')}
                              value={draft.review_status}
                              onChange={(event) => updateReview(candidate, { review_status: event.target.value as ReviewStatus })}
                            >
                              <MenuItem value="needs_info">{t('audiobook.sfxCandidateReview.needsInfo')}</MenuItem>
                              <MenuItem value="approved">{t('audiobook.promptAudioManualReview.passed')}</MenuItem>
                              <MenuItem value="rejected">{t('audiobook.sfxCandidateReview.rejected')}</MenuItem>
                            </Select>
                          </FormControl>
                          <TextField
                            size="small"
                            label={t('audiobook.sfxCandidateReview.localFileLabel')}
                            placeholder={t('audiobook.sfxCandidateReview.localFilePlaceholder')}
                            value={draft.local_file}
                            onChange={(event) => updateReview(candidate, { local_file: event.target.value })}
                            disabled={draft.review_status !== 'approved'}
                          />
                          <FormControl size="small" disabled={draft.review_status !== 'approved'}>
                            <InputLabel>{t('audiobook.sfxCandidateReview.categoryLabel')}</InputLabel>
                            <Select
                              label={t('audiobook.sfxCandidateReview.categoryLabel')}
                              value={draft.category}
                              onChange={(event) => updateReview(candidate, { category: event.target.value })}
                            >
                              <MenuItem value="">{t('audiobook.sfxCandidateReview.auto')}</MenuItem>
                              {SFX_CATEGORIES.map((item) => (
                                <MenuItem key={item} value={item}>{item}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                          <FormControl size="small" disabled={draft.review_status !== 'approved'}>
                            <InputLabel>{t('audiobook.sfxCandidateReview.styleLabel')}</InputLabel>
                            <Select
                              label={t('audiobook.sfxCandidateReview.styleLabel')}
                              value={draft.style}
                              onChange={(event) => updateReview(candidate, { style: event.target.value })}
                            >
                              <MenuItem value="">{t('audiobook.sfxCandidateReview.auto')}</MenuItem>
                              {SFX_STYLES.map((item) => (
                                <MenuItem key={item} value={item}>{item}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </Box>
                        <FormControlLabel
                          sx={{ mt: 0.5 }}
                          control={
                            <Checkbox
                              size="small"
                              checked={draft.license_verified}
                              onChange={(event) => updateReview(candidate, { license_verified: event.target.checked })}
                              disabled={draft.review_status !== 'approved'}
                            />
                          }
                          label={t('audiobook.sfxCandidateReview.licenseVerifiedLabel')}
                        />
                      </Box>
                    }
                  />
                </ListItem>
              )
            })}
          </List>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('action.close')}</Button>
        <Button
          variant="contained"
          startIcon={saving ? <CircularProgress size={16} color="inherit" /> : <PlaylistAddCheckIcon />}
          onClick={handleBuildManifest}
          disabled={saving || loading || candidates.length === 0 || approvedCount === 0}
        >
          {t('audiobook.sfxCandidateReview.buildManifest')}
        </Button>
        {approvedCount > 0 && (
          <Chip
            icon={<CheckCircleIcon />}
            label={t('audiobook.sfxCandidateReview.approvedCountLabel', {
              total: approvedCount,
            })}
            color="success"
            size="small"
          />
        )}
      </DialogActions>
    </Dialog>
  )
}

export default SfxCandidateReviewDialog
