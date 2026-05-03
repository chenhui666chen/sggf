import { apiClient } from '../../services/api'

interface CosyVoiceCloneUploadResponseData {
  url?: unknown
}

export const extractCosyVoiceCloneSampleUrl = (
  data?: CosyVoiceCloneUploadResponseData | null,
) => {
  const url = typeof data?.url === 'string' ? data.url : ''
  if (!url) {
    throw new Error('未返回临时URL')
  }
  return url
}

export const createRecordedCloneAudioFile = (
  blob: Blob,
  timestamp = Date.now(),
) => new File([blob], `recording_${timestamp}.webm`, { type: blob.type || 'audio/webm' })

export const uploadCosyVoiceCloneSampleFile = async (file: File) => {
  const res = await apiClient.uploadCosyVoiceV3PlusCloneSample(file)
  return extractCosyVoiceCloneSampleUrl(res.data)
}
