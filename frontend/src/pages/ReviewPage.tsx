import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Box,
  Card,
  CardContent,
  Button,
  TextField,
  Typography,
  Grid,
  LinearProgress,
  CircularProgress,
} from '@mui/material'
import SaveIcon from '@mui/icons-material/Save'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { RootState, AppDispatch } from '@/store/store'
import {
  fetchReview,
  createReview,
  updateReview,
} from '@/store/slices/reviewSlice'

export default function ReviewPage() {
  const { chapterId } = useParams<{ chapterId: string }>()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { reviews, isLoading } = useSelector((state: RootState) => state.review)
  const review = chapterId ? reviews[parseInt(chapterId)] : null
  const [formData, setFormData] = useState({
    overall_score: 7,
    story_score: 7,
    character_score: 7,
    language_score: 7,
    structure_score: 7,
    innovation_score: 7,
    feedback: '',
    suggestions: '',
    strengths: '',
  })

  useEffect(() => {
    if (chapterId) {
      dispatch(fetchReview(parseInt(chapterId)))
    }
  }, [dispatch, chapterId])

  useEffect(() => {
    if (review) {
      setFormData({
        overall_score: review.overall_score,
        story_score: review.story_score,
        character_score: review.character_score,
        language_score: review.language_score,
        structure_score: review.structure_score,
        innovation_score: review.innovation_score,
        feedback: review.feedback || '',
        suggestions: review.suggestions || '',
        strengths: review.strengths || '',
      })
    }
  }, [review])

  const handleSave = async () => {
    if (chapterId) {
      if (review) {
        await dispatch(updateReview({
          chapterId: parseInt(chapterId),
          data: formData,
        }))
      } else {
        await dispatch(createReview({
          chapterId: parseInt(chapterId),
          data: formData,
        }))
      }
    }
  }

  const ScoreField = ({ label, field }: { label: string; field: keyof typeof formData }) => (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="body2">{label}</Typography>
        <Typography variant="body2" color="primary">
          {formData[field]}/10
        </Typography>
      </Box>
      <LinearProgress
        variant="determinate"
        value={(formData[field] as number) * 10}
        sx={{ height: 8, borderRadius: 4 }}
      />
    </Box>
  )

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/dashboard')}
        >
          Back
        </Button>
        <Typography variant="h5">Chapter Review</Typography>
      </Box>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Quality Scores
              </Typography>
              <ScoreField label="Overall Score" field="overall_score" />
              <ScoreField label="Story Quality" field="story_score" />
              <ScoreField label="Character Development" field="character_score" />
              <ScoreField label="Language & Style" field="language_score" />
              <ScoreField label="Structure" field="structure_score" />
              <ScoreField label="Innovation" field="innovation_score" />
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Feedback
              </Typography>
              <TextField
                fullWidth
                label="Feedback"
                value={formData.feedback}
                onChange={(e) => setFormData({ ...formData, feedback: e.target.value })}
                multiline
                rows={3}
                margin="normal"
              />
              <TextField
                fullWidth
                label="Suggestions"
                value={formData.suggestions}
                onChange={(e) => setFormData({ ...formData, suggestions: e.target.value })}
                multiline
                rows={3}
                margin="normal"
              />
              <TextField
                fullWidth
                label="Strengths"
                value={formData.strengths}
                onChange={(e) => setFormData({ ...formData, strengths: e.target.value })}
                multiline
                rows={3}
                margin="normal"
              />
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Box sx={{ mt: 3, display: 'flex', gap: 2 }}>
        <Button
          variant="contained"
          color="primary"
          startIcon={<SaveIcon />}
          onClick={handleSave}
          fullWidth
        >
          Save Review
        </Button>
      </Box>
    </Container>
  )
}

