import { describe, expect, it } from 'vitest'

import {
  buildCharacterRelationsPayload,
  parseCharacterRelations,
} from '../characterRelations'

describe('characterRelations utils', () => {
  it('parses versioned payload items for editor usage', () => {
    const items = parseCharacterRelations({
      version: 2,
      current_summary: '顾晚：盟友；影舞：威胁',
      items: [
        { target: '顾晚', type: '盟友', description: '互相信任' },
        { target: '影舞', type: '威胁', detail: '威胁/持续观察' },
      ],
    })

    expect(items).toEqual([
      { target: '顾晚', type: '盟友', description: '互相信任', detail: '盟友/互相信任' },
      { target: '影舞', type: '威胁', detail: '威胁/持续观察' },
    ])
  })

  it('parses legacy target-type dictionaries', () => {
    const items = parseCharacterRelations({
      顾晚: '盟友',
      影舞: '威胁',
    })

    expect(items).toEqual([
      { target: '顾晚', type: '盟友', detail: '盟友' },
      { target: '影舞', type: '威胁', detail: '威胁' },
    ])
  })

  it('builds payload without dropping detail text', () => {
    const payload = buildCharacterRelationsPayload([
      { target: '顾晚', type: '盟友', description: '互相信任' },
      { target: '影舞', type: '威胁', detail: '威胁/持续观察' },
    ])

    expect(payload).toEqual({
      version: 2,
      text: '顾晚：盟友/互相信任；影舞：威胁/持续观察',
      current_summary: '顾晚：盟友；影舞：威胁',
      items: [
        { target: '顾晚', type: '盟友', description: '互相信任', detail: '盟友/互相信任' },
        { target: '影舞', type: '威胁', description: undefined, detail: '威胁/持续观察' },
      ],
    })
  })
})
