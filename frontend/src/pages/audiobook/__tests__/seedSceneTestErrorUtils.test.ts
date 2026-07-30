import { describe, expect, it } from 'vitest'

import { formatSeedSceneTestError } from '../seedSceneTestErrorUtils'

describe('Seed scene test error messages', () => {
  it('explains provider read timeouts without implying that billing did not happen', () => {
    const message = formatSeedSceneTestError('The read operation timed out')

    expect(message).toContain('600 秒')
    expect(message).toContain('可能已经受理或计费')
  })

  it('keeps unrelated errors actionable and unchanged', () => {
    expect(formatSeedSceneTestError('invalid prompt')).toBe('invalid prompt')
  })

  it('explains an interrupted provider audio download without suggesting Seed regeneration', () => {
    const message = formatSeedSceneTestError(
      'peer closed connection without sending complete message body',
    )

    expect(message).toContain('临时音频下载')
    expect(message).toContain('不会重新调用 Seed')
  })

  it('formats the stable backend audio download failure code', () => {
    const message = formatSeedSceneTestError(
      'audio_download_failed:RemoteProtocolError',
    )

    expect(message).toContain('连续下载失败')
    expect(message).toContain('可能已经计费')
  })
})
