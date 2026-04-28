import { describe, expect, it } from 'vitest'

import { normalizeMarkdownContent } from '../normalizeMarkdownContent'

describe('normalizeMarkdownContent', () => {
  it('将分卷标题和卷内字段标准化为 Markdown 结构', () => {
    const input = `## 五、分卷规划（共3卷）
【第1卷】 枯荣逆旅
章节规模：60-80章
卷定位：序幕与立足篇，展示世界观与主角核心能力。
下卷交接：地脉波动引来赤发老鬼的贪念与天律盟的正式调查。
【第2卷】 黑松诡影
章节规模：60-80章`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('### 【第1卷】 枯荣逆旅')
    expect(result).toContain('- **章节规模：** 60-80章')
    expect(result).toContain('- **卷定位：** 序幕与立足篇，展示世界观与主角核心能力。')
    expect(result).toContain('### 【第2卷】 黑松诡影')
    expect(result).not.toContain('下卷交接：地脉波动引来赤发老鬼的贪念与天律盟的正式调查。\n【第2卷】 黑松诡影')
  })

  it('保持原有 Markdown 列表不被重复改写', () => {
    const input = `## 五、分卷规划（共2卷）
【第1卷】 烬墟微光
- 章节规模：1-75章
- 核心目标：在边荒集市存活`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('### 【第1卷】 烬墟微光')
    expect(result).toContain('- 章节规模：1-75章')
    expect(result).toContain('- 核心目标：在边荒集市存活')
  })

  it('将章节细纲的 Markdown 列表字段补齐为加粗标题，恢复字段颜色渲染', () => {
    const input = `第93章 · 藏刃术（下）
- 场景目标：藏刃术收尾，完成内置化
- 关键事件：① 顾长庚完成最后一步调试
- 涉及人物：顾长庚、苏璃、铁面`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('- **场景目标：** 藏刃术收尾，完成内置化')
    expect(result).toContain('- **关键事件：** ① 顾长庚完成最后一步调试')
    expect(result).toContain('- **涉及人物：** 顾长庚、苏璃、铁面')
  })

  it('已是加粗字段的章节细纲列表保持稳定，不重复改写', () => {
    const input = `第94章 · 引爆之决
- **场景目标：** 铁面启动爆破装置
- **涉及人物：** 顾长庚、苏璃、铁面、陆南柯`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('- **场景目标：** 铁面启动爆破装置')
    expect(result).toContain('- **涉及人物：** 顾长庚、苏璃、铁面、陆南柯')
    expect(result.match(/\*\*场景目标：\*\*/g)?.length ?? 0).toBe(1)
  })

  it('将冒号落在粗体外的章节字段收敛为标准加粗字段', () => {
    const input = `第95章 · 管道逃亡
- **场景目标**：顾长庚带着苏璃沿排污管道逃离
- **关键事件**：① 黑水倒灌 ② 管壁崩裂
- **涉及人物**：顾长庚、苏璃`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('- **场景目标：** 顾长庚带着苏璃沿排污管道逃离')
    expect(result).toContain('- **关键事件：** ① 黑水倒灌 ② 管壁崩裂')
    expect(result).toContain('- **涉及人物：** 顾长庚、苏璃')
    expect(result).not.toContain('**场景目标**：')
  })

  it('普通 Markdown 内容保持稳定', () => {
    const input = `# 标题

## 小节
- 列表项`

    expect(normalizeMarkdownContent(input)).toBe(input)
  })

  it('将章节字段表格与损坏字段行收敛为稳定的列表格式', () => {
    const input = `| 字段 | 内容 |
| --- | --- |
| 场景目标 | 解开关于苏璃家族债务的石碑试炼并穿透迷宫，抵达封印室前最后一区域 |
| 冲突设计 | 苏璃内心对家族罪感的毁灭性崩塌 vs 以逻辑漏洞绕过天庄规则完成通透 |
| 关键事件 | ① 碑文清楚写明苏璃所在家族曾出力开发系统 |
| **涉及人物】 顾长庚、苏璃、丹丘生 | |
| 人物推进 | 苏璃开始主动承担家族秘密带来的代价 |
| **情节作用】 第二道试炼完结；直通封印室进入多路争夺 | |
| **结尾钩子】 丹丘生推开黑门，从二人视线中消失 | |`

    const result = normalizeMarkdownContent(input)

    expect(result).not.toContain('| 字段 | 内容 |')
    expect(result).not.toContain('| --- | --- |')
    expect(result).toContain('- **场景目标：** 解开关于苏璃家族债务的石碑试炼并穿透迷宫，抵达封印室前最后一区域')
    expect(result).toContain('- **冲突设计：** 苏璃内心对家族罪感的毁灭性崩塌 vs 以逻辑漏洞绕过天庄规则完成通透')
    expect(result).toContain('- **关键事件：** ① 碑文清楚写明苏璃所在家族曾出力开发系统')
    expect(result).toContain('- **涉及人物：** 顾长庚、苏璃、丹丘生')
    expect(result).toContain('- **人物推进：** 苏璃开始主动承担家族秘密带来的代价')
    expect(result).toContain('- **情节作用：** 第二道试炼完结；直通封印室进入多路争夺')
    expect(result).toContain('- **结尾钩子：** 丹丘生推开黑门，从二人视线中消失')
  })

  it('将无表格包裹的损坏字段行也修正为列表字段', () => {
    const input = `**涉及人物】 顾长庚、苏璃、丹丘生
**情节作用】 第二道试炼完结；直通封印室进入多路争夺
**结尾钩子】 丹丘生推开黑门，从二人视线中消失`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('- **涉及人物：** 顾长庚、苏璃、丹丘生')
    expect(result).toContain('- **情节作用：** 第二道试炼完结；直通封印室进入多路争夺')
    expect(result).toContain('- **结尾钩子：** 丹丘生推开黑门，从二人视线中消失')
  })

  it('将 Markdown 列表中的损坏章节字段修正为标准加粗字段', () => {
    const input = `- **涉及人物】 顾长庚、苏璃、丹丘生
- **情节作用】 第二道试炼完结；直通封印室进入多路争夺`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('- **涉及人物：** 顾长庚、苏璃、丹丘生')
    expect(result).toContain('- **情节作用：** 第二道试炼完结；直通封印室进入多路争夺')
  })
  it('能识别关键事件标题单独成行而内容续写在后续多行的格式', () => {
    const input = `第44章：城寨暗流

关键事件：
苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报
四天前秘密出城与斗篷人接头
发现其自身因果线被巧妙动过

伏笔事项：屏蔽装置的异常篡改手段为后续识别神秘人技术体系提供线索`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('- **关键事件：** 苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报 四天前秘密出城与斗篷人接头 发现其自身因果线被巧妙动过')
    expect(result).toContain('- **伏笔事项：** 屏蔽装置的异常篡改手段为后续识别神秘人技术体系提供线索')
  })

  it('能识别加粗字段标题单独成行而内容续写在后续多行的格式', () => {
    const input = `第96章 · 天降净罚

**关键事件**：
天庄战舰对白区进行净化打击
顾长庚带着苏璃躲入废坑暂避

**伏笔事项**：
净化光束对白区地貌的改写方式暴露了天庄底层扫描逻辑`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('- **关键事件：** 天庄战舰对白区进行净化打击 顾长庚带着苏璃躲入废坑暂避')
    expect(result).toContain('- **伏笔事项：** 净化光束对白区地貌的改写方式暴露了天庄底层扫描逻辑')
  })
})
