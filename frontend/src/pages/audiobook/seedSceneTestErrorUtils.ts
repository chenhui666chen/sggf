import type { TranslateFn } from './audioLibraryDisplay'

const PROVIDER_TIMEOUT_KEY = 'audiobook.seedSceneTestErrors.providerTimeout'
const INTERRUPTED_AUDIO_DOWNLOAD_KEY = 'audiobook.seedSceneTestErrors.interruptedAudioDownload'
const EXHAUSTED_AUDIO_DOWNLOAD_KEY = 'audiobook.seedSceneTestErrors.exhaustedAudioDownload'

const PROVIDER_TIMEOUT_MESSAGE = '豆包 Seed Audio 请求超过 600 秒仍未返回。供应商可能已经受理或计费，请不要立即重复生成；确认账单或等待供应商状态明确后，再使用刷新按钮重试。'
const INTERRUPTED_AUDIO_DOWNLOAD_MESSAGE = '豆包已返回结果，但临时音频下载连接中途断开。系统只会重试同一临时地址，不会重新调用 Seed；如果仍然失败，本次生成可能已经计费，请稍后再手动重试。'
const EXHAUSTED_AUDIO_DOWNLOAD_MESSAGE = '豆包已返回结果，但临时音频连续下载失败。系统没有重新调用 Seed，本次生成可能已经计费；请稍后再手动重试。'

export const formatSeedSceneTestError = (message: string, t?: TranslateFn) => {
  const normalized = String(message || '').toLowerCase()
  if (normalized.includes('audio_download_failed')) {
    return t ? t(EXHAUSTED_AUDIO_DOWNLOAD_KEY) : EXHAUSTED_AUDIO_DOWNLOAD_MESSAGE
  }
  if (
    normalized.includes('peer closed connection')
    || normalized.includes('complete message body')
  ) {
    return t ? t(INTERRUPTED_AUDIO_DOWNLOAD_KEY) : INTERRUPTED_AUDIO_DOWNLOAD_MESSAGE
  }
  if (
    normalized.includes('read operation timed out')
    || normalized.includes('provider_timeout')
    || normalized.includes('timed out')
  ) {
    return t ? t(PROVIDER_TIMEOUT_KEY) : PROVIDER_TIMEOUT_MESSAGE
  }
  return message
}
