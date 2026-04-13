import { describe, expect, it } from 'vitest'

import { exportChapterBreakdownToCSV } from '../expansionHelpers'

describe('exportChapterBreakdownToCSV', () => {
  it('按统一细纲字段导出章节 CSV', () => {
    const chapterBreakdown = `第1章：逐出青云，血染残卷
- 场景目标：林寒在废修绝境中觉醒共生之力。
- 冲突设计：林寒被御灵宗弟子围殴后被迫自救。
- 关键事件：
1. 林寒遭御灵宗弟子殴打
2. 兽皮残卷被鲜血激活
- 涉及人物：林寒、铁骨山猪
- 人物推进：林寒第一次确认自己能与妖兽共感。
- 情节作用：建立主角修行路径与世界核心矛盾。
- 信息落地：确认残卷与万兽低语存在联系。
- 结尾钩子：荒野深处似乎还有更高位的呼唤。`

    expect(exportChapterBreakdownToCSV(chapterBreakdown)).toBe(
      [
        '章节编号,标题,场景目标,冲突设计,关键事件,涉及人物,人物推进,情节作用,信息落地,结尾钩子',
        '1,逐出青云，血染残卷,林寒在废修绝境中觉醒共生之力。,林寒被御灵宗弟子围殴后被迫自救。,1. 林寒遭御灵宗弟子殴打 / 2. 兽皮残卷被鲜血激活,林寒、铁骨山猪,林寒第一次确认自己能与妖兽共感。,建立主角修行路径与世界核心矛盾。,确认残卷与万兽低语存在联系。,荒野深处似乎还有更高位的呼唤。',
      ].join('\n'),
    )
  })

  it('支持多章连续导出', () => {
    const chapterBreakdown = `第1章：开场
- 场景目标：主角入城。
- 涉及人物：林舟

第2章：试探
- 场景目标：主角试探黑市。
- 涉及人物：林舟、顾晚`

    expect(exportChapterBreakdownToCSV(chapterBreakdown)).toBe(
      [
        '章节编号,标题,场景目标,冲突设计,关键事件,涉及人物,人物推进,情节作用,信息落地,结尾钩子',
        '1,开场,主角入城。,,,林舟,,,,',
        '2,试探,主角试探黑市。,,,林舟、顾晚,,,,',
      ].join('\n'),
    )
  })
})
