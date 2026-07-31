import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'


describe('AITracePage detection score reuse', () => {
  const source = fs.readFileSync(
    path.resolve(process.cwd(), 'src/pages/AITracePage.tsx'),
    'utf8',
  )

  it('invalidates the detected score when the input text changes', () => {
    expect(source).toContain('const handleInputChange = useCallback')
    expect(source).toContain('setDetectResult(null)')
    expect(source).toContain('onChange={handleInputChange}')
    expect(source).toContain('text: detectedText')
    expect(source).toContain('detectResult.text === inputText')
  })
})
