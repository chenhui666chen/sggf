import { apiClient } from '../../services/api'

interface CloneSampleUploadResponseData {
  url?: unknown
}

export const extractCloneSampleUrl = (
  data?: CloneSampleUploadResponseData | null,
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

export const normalizeAudioMimeType = (value: string): string =>
  String(value || '').split(';', 1)[0].trim().toLowerCase()

const MIMO_CLONE_SUPPORTED_AUDIO_MIME_TYPES = new Set([
  'audio/mpeg',
  'audio/mp3',
  'audio/wav',
  'audio/x-wav',
  'audio/wave',
])

export const isMimoCloneSupportedAudioFile = (file: File): boolean => {
  const mimeType = normalizeAudioMimeType(file.type)
  if (MIMO_CLONE_SUPPORTED_AUDIO_MIME_TYPES.has(mimeType)) {
    return true
  }
  if (mimeType) {
    return false
  }
  const name = file.name.toLowerCase()
  return name.endsWith('.mp3') || name.endsWith('.wav')
}

const writeAscii = (view: DataView, offset: number, value: string) => {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index))
  }
}

export const encodePcm16Wav = (samples: Float32Array, sampleRate: number): Blob => {
  const channelCount = 1
  const bytesPerSample = 2
  const dataSize = samples.length * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buffer)

  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, channelCount, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * channelCount * bytesPerSample, true)
  view.setUint16(32, channelCount * bytesPerSample, true)
  view.setUint16(34, 16, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  let offset = 44
  samples.forEach((sample) => {
    const clamped = Math.max(-1, Math.min(1, sample))
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    offset += bytesPerSample
  })

  return new Blob([buffer], { type: 'audio/wav' })
}

const mixAudioBufferToMono = (audioBuffer: AudioBuffer): Float32Array => {
  const output = new Float32Array(audioBuffer.length)
  for (let channel = 0; channel < audioBuffer.numberOfChannels; channel += 1) {
    const channelData = audioBuffer.getChannelData(channel)
    for (let index = 0; index < audioBuffer.length; index += 1) {
      output[index] += channelData[index] / audioBuffer.numberOfChannels
    }
  }
  return output
}

type AudioContextConstructor = typeof AudioContext

const getAudioContextConstructor = (): AudioContextConstructor | null => {
  const win = globalThis as typeof globalThis & {
    webkitAudioContext?: AudioContextConstructor
  }
  return win.AudioContext || win.webkitAudioContext || null
}

export const convertRecordedAudioBlobToWavFile = async (
  blob: Blob,
  timestamp = Date.now(),
): Promise<File> => {
  const AudioContextCtor = getAudioContextConstructor()
  if (!AudioContextCtor) {
    throw new Error('当前浏览器无法将录音转换为 WAV，请上传 mp3 或 wav 文件')
  }

  const audioContext = new AudioContextCtor()
  try {
    const audioBuffer = await audioContext.decodeAudioData(await blob.arrayBuffer())
    const wavBlob = encodePcm16Wav(mixAudioBufferToMono(audioBuffer), audioBuffer.sampleRate)
    return new File([wavBlob], `recording_${timestamp}.wav`, { type: 'audio/wav' })
  } finally {
    void audioContext.close()
  }
}

const formatAudioFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export const summarizeAudioFile = (file: File): string => {
  const type = file.type || 'audio/*'
  const name = file.name || '音频样本'
  return `${name} · ${type} · ${formatAudioFileSize(file.size)}`
}

export const readAudioFileAsDataUrl = (file: File): Promise<string> => {
  if (!file.type.startsWith('audio/')) {
    return Promise.reject(new Error('请选择音频文件'))
  }

  return file.arrayBuffer()
    .then((buffer) => {
      const bytes = new Uint8Array(buffer)
      let binary = ''
      bytes.forEach((byte) => {
        binary += String.fromCharCode(byte)
      })
      return `data:${file.type};base64,${globalThis.btoa(binary)}`
    })
    .catch(() => {
      throw new Error('读取音频文件失败')
    })
}

export const uploadCosyVoiceCloneSampleFile = async (file: File) => {
  const res = await apiClient.uploadCosyVoiceV3PlusCloneSample(file)
  return extractCloneSampleUrl(res.data)
}
