import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf-8',
)

describe('UserCenter asset workspace source guards', () => {
  it('passes a stable feedback callback into the asset workspace view model', () => {
    const pageSource = readSource('../UserCenterPage.tsx')

    expect(pageSource).toContain('const handleAssetWorkspaceFeedback = useCallback(')
    expect(pageSource).toContain('publishFeedback: handleAssetWorkspaceFeedback')
    expect(pageSource).not.toContain('publishFeedback: (nextFeedback) => setFeedback(nextFeedback)')
  })
})
