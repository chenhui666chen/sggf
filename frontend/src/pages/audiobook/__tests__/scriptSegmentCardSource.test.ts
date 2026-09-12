import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const cardSource = readFileSync(
  new URL('../ScriptSegmentCard.tsx', import.meta.url),
  'utf8',
)

describe('ScriptSegmentCard selection affordance', () => {
  it('keeps segment selection separate from editing controls', () => {
    for (const marker of [
      'selected?: boolean',
      'onSelect?: (index: number) => void',
      'onFocusCapture={() => onSelect?.(index)}',
      'onClickCapture={() => onSelect?.(index)}',
      "borderColor: selected ? audiobookColors.primary : 'transparent'",
      "contentVisibility: 'auto'",
      "containIntrinsicSize: '220px'",
    ]) {
      expect(cardSource).toContain(marker)
    }
  })
})
