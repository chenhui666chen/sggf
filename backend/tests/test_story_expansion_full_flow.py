"""协同扩展全流程集成测试（离线确定性）。

验证三件事：
1. 完整 delta 扩展流程可跑通：计划 → 人物增量 → 大纲增量 → 自动对齐修复 → 合并落盘结构。
2. LLM 级人物-情节对齐验证在新协调路径生效：结果包含 character_plot_alignment，
   低分/冗余/缺失告警合并进 coordination_summary 与 alignment_warnings。
3. 高潮指示由大纲节奏驱动：扩展后大纲中带节奏标注的章（爆爽/卷末收束/小爽）
   生成对应大/小高潮指示；无标注章不注入硬性指令；并注入章节规划 prompt。

LLM 边界（_invoke_json/_invoke_text/validator LLM）脚本化，其余全部走真实代码路径。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from copy import deepcopy

from app.services.story_expansion_coord_pkg import StoryExpansionCoordinator


# ============================================================================
# 测试夹具：世界观 / 复杂人物关系网 / 46 章长大纲（超出旧截断预算）
# ============================================================================

WORLD_SETTING = """
九霄大陆，五大宗门并立：天玑阁（星象推演）、玄甲宗（兵修）、药王谷（丹道）、儒修书院（言出法随）、幽冥殿（魂修）。
三百年前观星台一夜覆灭，末代星官陈玄机携残卷逃入天玑阁，星官传承断代至今。
境界体系：炼气→筑基→金丹→元婴→化神→渡劫，每大境界三重小关。
资源体系：灵石为通货，星髓为顶层硬通货（仅观星台废墟出产），命火为魔道禁术燃料。
社会结构：宗门立于皇权之上，慕容太后以妖族遗脉之身掌控朝局，借玄甲军制衡宗门。
势力薄弱点：天玑阁星官传承断代，镇阁阵图残缺，是各方觊觎的破口。
文化禁忌：私窥星轨者为逆天者，人人得而诛之——这正是主角身份的最大红线。
封神遗局：观星台覆灭前布下的终极棋局，钥匙分散于血罗刹的魔刀与游方鉴定师墨家血脉中。
""".strip()


def _card(name, stance, position, faction, appearance, personality, background, motivation, ability, limitation, relations, mainline):
    return f"""### 【姓名】：{name}
【年龄/性别】：待补充
【故事立场】：{stance}
【角色定位】：{position}
【所属势力】：{faction}
【外貌锚点】：{appearance}
【性格锚点】：{personality}
【背景/当前处境】：{background}
【核心动机】：{motivation}
【能力与限制】：{ability} / 限制：{limitation}
【关键关系】：{relations}
【主线绑定】：剧情职责：{mainline} / 关联线索：观星台覆灭真相
---"""


CHARACTERS = "\n\n".join([
    _card("林昭", "主角方", "主角", "天玑阁",
          "粗布杂役服，眉心一点星痕，抬眼时有观星者的沉静",
          "外冷内热，认死理，对'天命'二字有近乎偏执的反抗欲",
          "观星台守陵人后裔，以杂役身份潜伏天玑阁三年，星痕渐显",
          "查清观星台覆灭真相，为守陵人一脉翻案",
          "星轨推演·残篇，可窥人命数三息", "每窥一次命数，自身寿元折损一月",
          "柳如烟：青梅竹马/她的双面身份让信任摇摇欲坠；陈玄机：师徒/他隐瞒了灭门案的关键真相；萧铁衣：死敌/夺鼎之争",
          "以凡人之躯逆推天命，撬动宗门与朝局的连环博弈"),
    _card("柳如烟", "中立方", "情报角色", "药王谷",
          "素白药童装束，腕间一串不起眼的铜铃",
          "温婉皮囊下是精密的利己计算，唯独对林昭的账算不清",
          "药王谷圣女，实为慕容太后安插的双面谍",
          "在太后与谷主的绞杀中为自己挣一条活路",
          "丹道天赋+毒术", "身份一旦坐实即遭两方灭口",
          "林昭：青梅竹马/她三次救他又三次出卖他；慕容太后：主仆/恩威并施的枷锁；秦无衣：暗卫/旧恩难却",
          "双面谍身份是卷二朝局线的引爆点"),
    _card("陈玄机", "主角方", "导师", "天玑阁",
          "鹤发星袍，常年独居观星残楼",
          "谨慎到近乎冷漠，用疏远保护学生",
          "末代星官，观星台覆灭唯一幸存者，背负三百年沉默",
          "在死前把星官传承与真相交到可信之人手上",
          "完整星轨推演", "寿元将尽，每次推演折寿一年",
          "林昭：师徒/以严苛掩饰愧疚；血罗刹：宿敌/灭门夜刀剑相向的旧怨；慕容太后：知情者/ mutually assured destruction",
          "灭门案活证人，卷三真相揭示的钥匙"),
    _card("萧铁衣", "反派方", "对手", "玄甲军",
          "玄铁重甲，面有旧疤，声如磨铁",
          "兵修的直与傲，信奉'力即秩序'",
          "慕容太后义子，吞灵体质，玄甲军少帅",
          "夺观星台鼎，证明自己配得上义母的棋局",
          "吞灵体质+玄甲兵阵", "吞灵反噬，每月需镇压一次",
          "林昭：死敌/夺鼎之争；慕容太后：义母子/忠诚里掺着恐惧；苏慕白：仇敌/杀弟之仇",
          "卷一卷二的直接压力源"),
    _card("慕容太后", "反派方", "高位反派", "朝局",
          "凤袍垂珠，眼尾一点妖纹",
          "百年妖修的耐心，把所有人在棋盘上看成棋子",
          "妖族遗脉，操控朝局三百年，与观星台覆灭直接相关",
          "集齐封神遗局钥匙，让妖族重归九霄",
          "千年道行+人心操盘", "妖脉惧星轨推演，林昭是天敌",
          "萧铁衣：义子/最锋利也最危险的棋；柳如烟：暗子/随时可弃；阿蛮：血脉仆从/忠于她又惧她",
          "幕后主反派，贯穿三卷"),
    _card("血罗刹", "亦正亦邪", "危险盟友", "魔道散修",
          "赤发覆面，背缚魔刀'饮星'",
          "暴烈直率，恩怨分明，讨厌弯绕",
          "灭门夜的执刀人之一，被欺瞒，被利用，被放逐",
          "找当年下棋的人算总账",
          "魔刀饮星+不死魔躯", "魔刀认主血契，挥刀即噬主",
          "陈玄机：宿敌/灭门夜真相各执一词；慕容太后：被利用者/最大恨源；墨七：旧识/如今互相怀疑",
          "封神遗局钥匙持有者之一"),
    _card("苏慕白", "主角方", "盟友", "儒修书院",
          "青衫折扇，笑面藏锋",
          "风趣是其保护色，底线极硬",
          "书院天才，弟弟死于萧铁衣军演",
          "用阵法与谋略让玄甲军付出代价",
          "言出法随·阵道", "言灵有次数上限，用尽则喑",
          "萧铁衣：仇敌/杀弟之仇不共戴天；林昭：盟友/相互试探后的托付",
          "卷二战阵线的核心助力"),
    _card("秦无衣", "亦正亦邪", "情报角色", "夜枭",
          "灰衣不起眼，惯于站在阴影里",
          "沉默，记恩，把承诺看得比命重",
          "杀手组织'夜枭'首领，幼年受柳家活命之恩",
          "还清柳家恩情，带夜枭脱离太后控制",
          "暗杀网络+易容", "恩情未清前行动受制",
          "柳如烟：护主/恩义的枷锁；慕容太后：合作者/随时翻脸",
          "卷二翻转局的关键暗手"),
    _card("阿蛮", "中立方", "守护者", "妖族遗脉",
          "兽瞳少女，腕上妖纹灼灼",
          "懵懂，忠诚，正在学习'自己选'",
          "慕容太后血脉仆从，奉命贴身监视林昭",
          "弄清'忠诚'与'自我'的边界",
          "妖化强躯", "血脉令环在太后手中，抗命即遭反噬",
          "慕容太后：主仆/血脉枷锁；林昭：监视对象/却被其感化",
          "卷三妖族线的人形切口"),
    _card("顾长风", "反派方", "初期对手", "天玑阁",
          "锦袍玉冠，天玑阁大师兄",
          "傲慢，嫉妒，但在大是大非前会动摇",
          "阁主亲传，视林昭为窃取传承的贼",
          "夺回大师兄尊严，证明自己是正统",
          "阁内功法大圆满", "心气高于天赋，易被撩拨",
          "林昭：对手/从踩踏到被迫正视",
          "卷一宗门内部压力线，卷三有策反空间"),
])


def _ch(n, title, scene, conflict, events, chars, progress, function, hook, highlight="", foreshadow="无"):
    lines = [
        f"第{n}章：{title}",
        f"- 场景目标：{scene}",
        f"- 冲突设计：{conflict}",
        f"- 关键事件：{events}",
        f"- 涉及人物：{chars}",
        f"- 人物推进：{progress}",
        f"- 情节作用：{function}",
        f"- 结尾钩子：{hook}",
    ]
    if highlight:
        lines.append(f"- 爽点类型：{highlight}")
    lines.append(f"- 伏笔事项：{foreshadow}")
    return "\n".join(lines)


_VOL1 = [
    ("杂役星痕", "天玑阁杂役院，林昭半夜擦拭星图残碑，星痕初显", "管事克扣月例→星痕反噬→被顾长风当众刁难", "星痕初显；残碑认主；顾长风结怨", "林昭、顾长风", "林昭发现自己与观星台的渊源", "开局定调", "残碑浮出一行星文：'守陵人归位'", "", "守陵人身份线开启"),
    ("药童铜铃", "药王谷使团到访，柳如烟以药童身份现身", "使团试探天玑阁→林昭识破药中机关→两人旧识相认又不敢相认", "使团来访；识破机关；旧识重逢", "林昭、柳如烟、陈玄机", "柳如烟的双面身份埋下第一道裂缝", "关系铺垫", "铜铃三响，是杀局也是约定的旧暗号", "", "铜铃暗号线开启"),
    ("阁老收徒", "观星残楼，陈玄机以'打扫残楼'名义接近林昭", "阁内反对声→星轨推演切磋→以残篇收徒", "残楼传艺；星轨推演·残篇入门", "林昭、陈玄机", "师徒名分暗立", "传承线启动", "陈玄机独白：'三百年了，终于等到'", "", "陈玄机与灭门案的关联暗埋"),
    ("宗门大比·预选", "演武场，杂役组预选", "顾长风设局淘汰林昭→星痕窥命数破局", "预选晋级；窥命代价初显", "林昭、顾长风", "林昭学会为赢付出代价", "升级铺垫", "寿元折损的代价被陈玄机看在眼里", "", "窥命代价线强化"),
    ("玄甲巡边", "宗门边界，玄甲军巡边挑衅", "边界摩擦→萧铁衣登场→吞灵体质威慑全场", "边界对峙；萧铁衣注意到林昭", "林昭、萧铁衣", "死敌第一次对视", "反派压力引入", "萧铁衣：'有趣的命数'", "", "吞灵反噬伏笔：他按住了自己的手腕"),
    ("星文破译", "残楼，师徒破译残碑星文", "星文残缺→柳如烟送药引线索→破译推进", "星文推进；观星台废墟方位浮出", "林昭、陈玄机、柳如烟", "柳如烟第一次'私心'帮他", "信息揭示", "星文最后一句指向废墟下的'鼎'", "", "观星台之鼎伏笔"),
    ("大师兄的算计", "藏经阁，顾长风设局构陷林昭窃法", "构陷→对质→星痕当众显威翻盘", "构陷风波；当众翻盘", "林昭、顾长风", "顾长风从轻蔑转为记恨", "小冲突兑现", "顾长风暗中投书玄甲军", "", "顾长风黑化引线"),
    ("废墟初探", "观星台废墟外围夜探", "守阵残余→阿蛮奉命拦截→不打不相识", "废墟夜探；初遇阿蛮", "林昭、阿蛮", "阿蛮第一次对'目标'产生好奇", "妖族线切入", "废墟深处传来鼎鸣", "", "封神遗局初现"),
    ("谷主寿宴", "药王谷寿宴，各方齐聚", "宴上交锋→柳如烟被迫两线演戏→林昭看破不说破", "寿宴交锋；双面谍处境具象化", "林昭、柳如烟、慕容太后（远程）", "林昭确认她的处境，信任反而加深", "关系深化", "太后赐下的礼物里藏着催命符", "", "太后与如烟的主仆线明化"),
    ("镇阁阵图", "天玑阁镇阁大阵异动", "阵图残缺→星文补阵→阁主动摇", "补阵立功；阁内地位跃升", "林昭、陈玄机、顾长风", "从杂役到'阵图参修'", "地位升级", "阵图补全的最后一笔，需要守陵人之血", "", "守陵人血脉伏笔"),
    ("魔刀夜访", "血罗刹夜闯残楼", "刀剑相向→灭门夜各执一词→不欢而散却互留一线", "夜闯对峙；灭门案罗生门", "陈玄机、血罗刹、林昭", "师父的另一面浮出", "真相迷雾加深", "血罗刹留下半块星纹铁牌", "", "封神遗局钥匙之一现身"),
    ("妖纹少女", "后山，阿蛮私自找林昭", "血脉令环刺痛→她仍开口示警→太后震怒", "阿蛮示警；太后惩戒", "阿蛮、林昭", "阿蛮第一次违令", "妖族线深化", "令环的反噬在她腕上刻下新纹", "", "血脉枷锁机制明化"),
    ("大比·正赛", "宗门大比正赛", "顾长风暗联手玄甲细作→林昭星痕全开", "正赛对决；细作搅局", "林昭、顾长风", "顾长风败得心服口不服", "关键转折", "细作落网前咬毒自尽，线索指向玄甲军", "", "宗门与军方勾结线"),
    ("细作罗网", "顺藤摸瓜查细作网络", "网状清剿→牵出朝局影子→阁主下令止步", "清剿细作；止步朝局", "林昭、陈玄机、苏慕白（远程信件）", "苏慕白书信结盟", "盟友引入", "止步令背后是阁主的恐惧", "", "阁主的秘密伏笔"),
    ("宗门大比·夺魁", "大比决赛，林昭对阵顾长风背后的玄甲客卿", "客卿以吞灵压制→窥命三息+星痕共鸣→越级夺魁", "决赛夺魁；客卿败退", "林昭、顾长风、萧铁衣（观礼）", "林昭名动五宗", "小高潮顶点", "萧铁衣观礼席上轻笑：'鼎，快出土了'", "爆爽（越级夺魁，当众打脸）", ""),
    ("卷末·残楼夜话", "残楼，师徒摊牌", "真相半揭→陈玄机寿元将尽→传承正式交付", "摊牌；传承交付", "林昭、陈玄机", "师徒名分落定，真相未完", "卷末收束", "'卷二，去朝局里把我没下完的棋下完'", "卷末收束·余韵", "卷二朝局线启动"),
]

_VOL2 = [
    ("入京", "林昭以阵图参修身份随阁中使团入京", "京城盘查→太后召见→言语交锋", "入京；太后召见", "林昭、慕容太后", "与幕后主反派的第一次正面", "新地图开启", "太后指尖敲着凤椅：'像，太像了'", "", "'像谁'悬念"),
    ("夜枭暗记", "京城夜市，秦无衣留暗记约见", "暗记追查→夜枭现身→情报交易", "结识秦无衣；情报交易", "林昭、秦无衣", "与暗线结盟", "暗手引入", "秦无衣只问一句：'她最近好吗'", "", "秦无衣-柳家恩义线"),
    ("玄甲演武", "玄甲军演武场外的对峙", "萧铁衣约战→吞灵对星轨→两败俱伤", "约战；吞灵反噬公开化", "林昭、萧铁衣", "死敌之间生出忌惮", "反派立体化", "反噬发作时，萧铁衣想起义母的警告", "", "义母子裂痕伏笔"),
    ("书院来客", "苏慕白进京，言灵初显", "书院讲学→暗讽军方→兄弟旧案提起", "苏慕白入局；旧案公开", "苏慕白、萧铁衣", "杀弟之仇摆上台面", "盟友线汇合", "折扇合拢：'下一阵，请玄甲军务必再来'", "", "战阵对决预告"),
    ("丹房迷局", "药王谷驻京丹房出事，柳如烟被构陷", "构陷→太后弃子试探→林昭强行作保", "丹房风波；弃子试探", "柳如烟、林昭、慕容太后", "如烟第一次被'保'", "关系压力测试", "作保的代价：林昭欠下人情债", "", "人情债去向伏笔"),
    ("夜枭换防", "太后调夜枭执行脏活", "调令与恩义冲突→秦无衣拖延→太后起疑", "换防危机；太后起疑", "秦无衣、慕容太后", "暗手开始离心", "暗线松动", "拖延的理由编了三个，太后只信第一个", "", "夜枭倒戈预备"),
    ("阵前叫阵", "京城外军演，书院与玄甲对阵", "叫阵→小胜→军方撕破脸", "文武对阵；小胜", "苏慕白、萧铁衣", "军方颜面扫地", "小高潮", "萧铁衣当场请旨：'请诛妖言者'", "小爽（言灵破阵）", ""),
    ("血脉令环", "太后催动令环，阿蛮濒死", "催环→林昭星轨干预→令环出现裂痕", "催环危机；干预成功", "阿蛮、林昭、慕容太后", "阿蛮彻底倒向林昭", "妖族线转折", "裂痕意味着太后血契并非无解", "", "血契可破伏笔"),
    ("鼎讯", "观星台废墟下之鼎将出土的消息走漏", "各方争抢→阁主密令→先遣队组建", "鼎讯走漏；先遣队", "林昭、顾长风、萧铁衣", "三方争夺布局", "爆点前置", "废墟上空星轨紊乱，天象示警", "", "天象示警伏笔"),
    ("旧怨重燃", "血罗刹入京寻仇", "寻仇→各执一词的灭门夜再次对质→太后渔利", "寻仇对质", "血罗刹、陈玄机（远程）、慕容太后", "罗生门加深", "真相迷雾", "太后书房里挂着灭门夜的作战图", "", "太后即幕后之一实锤预备"),
    ("茶楼博弈", "四方茶楼暗谈", "多方试探→情报互换→各留底牌", "暗谈博弈", "林昭、柳如烟、秦无衣、苏慕白", "松散同盟成型", "布局汇合", "同盟的第一条约定：不问彼此的底线", "", "同盟脆弱性伏笔"),
    ("演武刺杀", "军演刺杀局，目标苏慕白", "刺杀→夜枭暗中掉包→言灵救场", "刺杀局；掉包", "苏慕白、秦无衣、萧铁衣", "夜枭站队明朗化", "暗线发力", "掉包的死士身上有太后私印", "", "私印证据链"),
    ("私印风暴", "私印证据呈交朝堂", "证据攻防→太后断尾→宗门被迫表态", "朝堂攻防；断尾求生", "林昭、慕容太后、阁主", "朝局全面摊牌", "中高潮", "断尾的'尾'，是柳如烟", "中爽（朝堂翻盘）", ""),
    ("断尾求生", "柳如烟被推出去顶罪", "顶罪局→三方抢人→如烟自曝双面身份", "顶罪；自曝", "柳如烟、林昭、慕容太后", "如烟身份全面公开", "关系大转折", "'我三次救你，也三次卖你，这次两清'", "", "两清之后呢"),
    ("血遁千里", "护送如烟出京", "追杀→血罗刹意外驰援→三败俱伤", "千里血遁；驰援", "林昭、柳如烟、血罗刹", "血罗刹立场软化", "亦敌亦友转折", "驰援的理由：'我不想再欠星官的了'", "", "灭门夜真相将揭预备"),
    ("卷末·朝局收官", "朝局线收官，鼎出土在即", "太后暂退→玄甲接管→联军赴废墟", "朝局收官；联军集结", "全体", "卷三全员就位", "卷末收束", "废墟上空，星轨彻底紊乱", "卷末收束·爆爽（朝堂翻盘收官）", "卷三秘辛线启动"),
]

_VOL3 = [
    ("废墟掘鼎", "观星台废墟联合掘鼎", "掘鼎分工暗斗→鼎中无物→星轨异变", "掘鼎；鼎中无物", "林昭、萧铁衣、顾长风", "所有人扑空", "反转开局", "鼎里只有一行刻字：'局中局'", "", "封神遗局真意悬念"),
    ("局中局", "残楼推演局中局", "推演→陈玄机寿元燃尽式演算→三百年前的另一半真相", "真相半揭", "林昭、陈玄机", "师父油尽灯枯", "真相揭示·大段", "'灭门夜，不是我逃了，是我被放走了'", "", "放走他的人是谁"),
    ("星官血债", "血罗刹听到另一半真相", "真相冲击→魔刀暴走→血罗刹自锁", "真相冲击", "血罗刹、陈玄机", "宿敌变同受害者", "关系重构", "魔刀'饮星'自己震颤不止", "", "钥匙共鸣伏笔"),
    ("妖脉溯源", "阿蛮讲妖族口述史", "口述史与星图互证→太后目的浮出", "溯源互证", "阿蛮、林昭", "阿蛮完成'自己选'", "世界观揭示", "妖族要回的不是天下，是'名分'", "", "妖族真正诉求"),
    ("钥匙齐聚", "墨家鉴定师墨七现身废墟黑市", "钥匙争夺→墨七坐地起价→三方围杀", "墨七入场；围杀", "林昭、血罗刹、慕容太后（遥控）", "最后钥匙现身", "新变量入场", "墨七只鉴宝，不卖命", "", "墨家血脉与遗局的关系"),
    ("阁主之秘", "阁主深夜密会太后信使", "密会被撞破→阁主摊牌→宗门内裂", "内裂", "阁主、林昭、顾长风", "阁主'止步令'真相大白", "内鬼揭示", "阁主：'我守的不是阁，是当年没打完的赌'", "", "三百年前的赌局"),
    ("鼎鸣夜宴", "废墟夜宴，各方最后试探", "夜宴→刺杀再起→阿蛮挡刀", "夜宴刺杀", "阿蛮、林昭、萧铁衣", "阿蛮血契彻底断裂", "情感高潮·大", "断裂的令环碎成星屑", "小爽（血契断裂）", "令环碎片用途"),
    ("军帅倒戈", "萧铁衣发现义母真面目", "反噬病发→太后弃子→萧铁衣携军投诚", "倒戈", "萧铁衣、林昭、慕容太后", "死敌变盟友", "大反转", "'我不是投你，我是投个说法'", "", "玄甲军整编伏笔"),
    ("遗局终章·上", "遗局终局启动前夜", "终局部署→诀别信→星轨归位", "终局前夜", "全体", "全员就位", "大高潮前置", "陈玄机把最后的寿元折成了三息推演", "", "三息推演用途"),
    ("遗局终章·下", "封神遗局终局启动", "终局对峙→三息推演逆转→太后底牌尽出", "终局对峙；逆转", "林昭、慕容太后、洛清霜（暗子）", "卷三收官", "本卷大高潮收束", "'第二局，开始了'", "大高潮前置", "第二局=卷四"),
    ("星屑余烬", "战后清点", "伤亡清点→同盟分赃→暗线收束", "清点收束", "全体", "各方各怀心思", "过渡收束", "墨七不告而别，带走一样东西", "", "墨七带走之物"),
    ("新卷启程", "卷四启程", "新格局→新目标→队伍重整", "启程", "林昭、柳如烟、萧铁衣", "阵营重组完成", "卷末收束·新篇", "星轨重归清明，唯余一点浊星", "卷末收束·余韵", "浊星即卷四主威胁"),
]


def _build_outline():
    blocks = []
    n = 1
    for vol in (_VOL1, _VOL2, _VOL3):
        for row in vol:
            blocks.append(_ch(n, *row))
            n += 1
    prefix = (
        "# 全书结构\n"
        "- 卷一（第1-16章）宗门生存：星痕觉醒→宗门大比夺魁→传承交付\n"
        "- 卷二（第17-32章）朝局入局：京城博弈→私印风暴→朝堂翻盘\n"
        "- 卷三（第33-46章）秘辛揭开：局中局→钥匙齐聚→遗局终章\n"
        "- 整体节奏：小爽→压抑→中爽→再压抑→爆爽→余韵\n"
    )
    return prefix + "\n\n" + "\n\n".join(blocks)


LONG_OUTLINE = _build_outline()
assert len(LONG_OUTLINE) > 5000, "测试夹具大纲必须超过旧 5000 字符截断预算，否则预算断言无意义"


# ============================================================================
# 脚本化 LLM 应答（结构与真实 prompt 约定的 JSON schema 完全一致）
# ============================================================================

# 实际章节数：卷一 1-16 / 卷二 17-32 / 卷三 33-44，共 44 章，目标扩展到 48 章
PLAN_JSON = {
    "strategy": "balanced",
    "summary": "卷三收官增量：补反派军师与中立变量，新增4章收束封神遗局第一局",
    "outline_ops": [{
        "action": "append",
        "after_chapter": None,
        "count": 4,
        "goal": "封神遗局第一局收束：太后底牌尽出，联军反击，卷四引线埋设",
        "focus_characters": ["林昭", "洛清霜"],
        "notes": "承接第41-44章终局线",
    }],
    "character_ops": [
        {
            "role_position": "高位反派",
            "purpose": "统合太后党与玄甲残军的军师型角色，补足反派决策层",
            "related_existing": ["慕容太后", "萧铁衣"],
            "serve_chapter_hint": "第45-48章",
        },
        {
            "role_position": "中立变量",
            "purpose": "墨家鉴定师，封神遗局钥匙相关，立场摇摆",
            "related_existing": ["血罗刹", "林昭"],
            "serve_chapter_hint": "第45-48章",
        },
    ],
    "relationship_ops": [
        {"source": "洛清霜", "target": "慕容太后", "type": "利用", "description": "以谋略互为刀"},
        {"source": "墨七", "target": "血罗刹", "type": "怀疑", "description": "旧识成疑"},
    ],
}

CHARS_JSON = {
    "characters": [
        {
            "name": "洛清霜",
            "age_gender": "年龄不详/女",
            "story_stance": "反派方",
            "role_position": "高位反派",
            "affiliation": "太后党幕僚团",
            "appearance_anchor": "素纱覆眼，执白玉棋枰",
            "personality_anchor": "温声细语，落子无情",
            "background_status": "前朝遗臣之后，被太后收为首席谋士",
            "motivation": "借太后的局复前朝之国",
            "ability_outline": "人心推演+军阵谋略",
            "limitation": "双目失明，依赖情报网",
            "key_relationships": "慕容太后：互相利用；萧铁衣：旧部兼棋子",
            "mainline_role": "反派决策层大脑，卷四主谋预备",
            "mainline_clues": "封神遗局第二局执棋人",
            "growth_direction": "从执棋人变棋子再翻盘",
        },
        {
            "name": "墨七",
            "age_gender": "中年/男",
            "story_stance": "中立方",
            "role_position": "中立变量",
            "affiliation": "墨家游方一脉",
            "appearance_anchor": "灰袍补丁摞补丁，指间老茧",
            "personality_anchor": "只认器物不认人，规矩比命硬",
            "background_status": "墨家鉴定师，携遗局钥匙之一流亡江湖",
            "motivation": "守墨家'器不助虐'的祖训",
            "ability_outline": "器物鉴定+机关术",
            "limitation": "不修战力，遇武则遁",
            "key_relationships": "血罗刹：旧识/互相怀疑；林昭：交易关系",
            "mainline_role": "钥匙看门人，决定遗局何时开启",
            "mainline_clues": "第45章黑市围杀的真正目标",
            "growth_direction": "从守规矩到破规矩",
        },
    ],
    "relationship_patch": [
        {"source": "洛清霜", "target": "慕容太后", "type": "利用", "description": "以谋略互为刀"},
        {"source": "墨七", "target": "血罗刹", "type": "怀疑", "description": "旧识成疑"},
        {"source": "墨七", "target": "林昭", "type": "交易", "description": "鉴宝换庇护"},
    ],
}

# 注意：墨七 故意不出现在任何新增章节的 involved_characters 中 → 触发自动对齐修复
CHAPTERS_JSON = {
    "chapters": [
        {
            "title": "浊星天谕",
            "scene_goal": "残楼，星轨重算浊星方位",
            "conflict_design": "①浊星坐标缺失 → ②陈玄机遗稿残页 → ③锁定北荒",
            "key_events": "遗稿解读；浊星定位；北荒启程预备",
            "involved_characters": ["林昭", "苏慕白"],
            "character_progress": "林昭接过推演衣钵",
            "plot_function": "卷四引线开启",
            "ending_hook": "浊星的方位，指向北荒一座不该存在的城",
            "highlight_type": "",
            "foreshadowing_item": "北荒之城",
        },
        {
            "title": "盲棋入局",
            "scene_goal": "太后别苑，洛清霜首次执棋",
            "conflict_design": "①残军无首 → ②盲棋布阵 → ③反手清算旧部",
            "key_events": "洛清霜接盘残军；清洗异己；剑指联军",
            "involved_characters": ["林昭", "洛清霜", "萧铁衣"],
            "character_progress": "反派阵营完成换代",
            "plot_function": "新反派立威",
            "ending_hook": "棋枰落子声里，萧铁衣旧部一夜易帜",
            "highlight_type": "",
            "foreshadowing_item": "易帜军符去向",
        },
        {
            "title": "阵前倒戈",
            "scene_goal": "联军大营，易帜军清算夜",
            "conflict_design": "①旧部哗变 → ②顾长风阵前倒戈 → ③哗变反成投名状",
            "key_events": "哗变夜；顾长风反正；军心重聚",
            "involved_characters": ["林昭", "顾长风", "秦无衣"],
            "character_progress": "顾长风完成从对手到盟友的转身",
            "plot_function": "旧对手线收束",
            "ending_hook": "顾长风递上的名单里，第一个名字是柳如烟",
            "highlight_type": "小爽（顾长风阵前倒戈）",
            "foreshadowing_item": "名单背后的告密者",
        },
        {
            "title": "遗局第二局",
            "scene_goal": "观星台废墟，封神遗局第二局开演",
            "conflict_design": "①洛清霜借局反噬太后 → ②三息推演续命一搏 → ③林昭联手反杀",
            "key_events": "第二局开启；太后底牌尽出；联手反杀收官",
            "involved_characters": ["林昭", "洛清霜", "慕容太后", "阿蛮"],
            "character_progress": "太后时代落幕，洛清霜执第二局",
            "plot_function": "本卷大高潮收束",
            "ending_hook": "'第二局的赌注，是整个九霄'",
            "highlight_type": "爆爽（观星台遗阵启动，联手反杀）",
            "foreshadowing_item": "回收第16章'没下完的棋'",
        },
    ]
}

VALIDATOR_MD = """## 匹配度评分
总分：58/100

## 冗余人物
- 顾长风：卷三第33章后退居幕后，第48章倒戈前无明确情节职责

## 缺失人物
- 反派军师型角色：需要一个能统合太后党残局的决策层角色

## 关系合理性问题
- 秦无衣对柳家的恩义线未在卷二之后的章节落地

## 改进建议
1. 为顾长风在第34-48章补充至少两处情节职责
2. 反派决策层需要新角色填补萧铁衣倒戈后的空缺
3. 秦无衣的恩义线应在卷三安排一次回收"""


# ============================================================================
# 脚本化协调器：LLM 边界替换，流程代码全真
# ============================================================================

class ScriptedCoordinator(StoryExpansionCoordinator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.captured_prompts = []

    def _configure_story_expansion_runtime_models(self, *args, **kwargs):
        # 离线测试：模型选型/运行时 LLM 构建不参与（invoke 已脚本化，无需真实客户端）
        return None

    def _invoke_json(self, prompt, fallback=None):
        self.captured_prompts.append(prompt)
        if "协同拓展架构师" in prompt:
            return deepcopy(PLAN_JSON)
        if "小说人物协同设计师" in prompt:
            return deepcopy(CHARS_JSON)
        if "小说章节拓展策划师" in prompt:
            return deepcopy(CHAPTERS_JSON)
        return dict(fallback or {})

    def _invoke_chapter_json(self, prompt, fallback=None, **kwargs):
        # 章节卡批量调用走独立预算入口，脚本化逻辑与 _invoke_json 一致
        return self._invoke_json(prompt, fallback=fallback)

    def _invoke_text(self, prompt, **kwargs):
        self.captured_prompts.append(prompt)
        return ""


_RUN_CACHE = {}


def _run_full_expansion(monkeypatch):
    """跑一次完整 delta 扩展（全局只跑一次，两个测试复用）。"""
    if "result" in _RUN_CACHE:
        return _RUN_CACHE

    import app.services.agents.character_plot_validator as cpv_module

    captured = {}

    class FakeValidatorLLM:
        def invoke(self, prompt):
            captured["validator_prompt"] = prompt

            class _R:
                content = VALIDATOR_MD

            return _R()

    # validator 走真实 prompt/解析/合并路径，只替换其 LLM 客户端
    monkeypatch.setattr(cpv_module, "create_task_llm", lambda **kwargs: FakeValidatorLLM())

    coord = ScriptedCoordinator(project_id=999999, genre="修真", planned_chapters_max=48)
    result = coord.execute(
        current_outline=LONG_OUTLINE,
        characters=CHARACTERS,
        world_setting=WORLD_SETTING,
        target_total_chapters=48,
        target_total_characters=12,
        strategy="auto",
        expansion_mode="auto",
    )
    _RUN_CACHE["result"] = result
    _RUN_CACHE["coord"] = coord
    _RUN_CACHE["validator_prompt"] = captured.get("validator_prompt", "")
    return _RUN_CACHE


# ============================================================================
# 测试 1：完整扩展流程 + 人物-情节对齐生效
# ============================================================================

def test_full_delta_expansion_and_alignment(monkeypatch):
    bundle = _run_full_expansion(monkeypatch)
    result = bundle["result"]
    coord = bundle["coord"]

    # --- 扩展流程核心结构 ---
    assert result["execution_mode"] == "delta"
    # 新增章节 45-48 进入合并后大纲（44 章存量 + 4 章增量）
    for n in (45, 46, 47, 48):
        assert f"第{n}章：" in result["plot_outline"], f"合并大纲缺少第{n}章标题行"
    # 新增人物卡合并 + 关系补丁产出
    assert "### 【姓名】：洛清霜" in result["characters"]
    assert "### 【姓名】：墨七" in result["characters"]
    assert set(result["new_characters"]) >= {"洛清霜", "墨七"}
    assert result["character_relationships"], "关系补丁未产出"
    # 墨七未在新章节中出场 → 自动对齐修复应触发
    assert any("墨七" in str(item) for item in result.get("alignment_repairs") or []), (
        "自动对齐修复未触发（墨七应被补引用）"
    )

    # --- LLM 人物-情节对齐验证生效（新协调路径） ---
    alignment = result.get("character_plot_alignment")
    assert alignment, "execute() 后处理未注入 character_plot_alignment"
    assert alignment["score"] == 58
    assert any("顾长风" in str(item) for item in alignment["redundant_characters"])
    assert any("军师" in str(item) for item in alignment["missing_characters"])
    # 告警合并：summary + alignment_warnings
    assert "【人物-情节对齐】" in result["coordination_summary"]
    assert "58/100" in result["coordination_summary"]
    assert any("人物-情节对齐" in str(w) for w in result.get("alignment_warnings") or [])

    # --- 上下文预算生效（大纲约7000字符>旧5000预算，末章完整可见） ---
    plan_prompt = next(p for p in coord.captured_prompts if "协同拓展架构师" in p)
    assert "第44章" in plan_prompt, "扩展计划 prompt 未见大纲末章（旧5000预算会截断）"
    assert "第44章" in plan_prompt.split("【当前大纲原文】")[-1] or "新卷启程" in plan_prompt, "末章应出现在原文区块"
    validator_prompt = bundle["validator_prompt"]
    assert "第44章" in validator_prompt, "对齐验证 prompt 未见大纲末章（旧2000预算会截断）"
    assert "秦无衣" in validator_prompt, "对齐验证 prompt 未见完整人物名单"


# ============================================================================
# 测试 2：高潮指示由大纲节奏驱动（基于扩展后大纲）
# ============================================================================

def test_outline_driven_climax_instruction(monkeypatch):
    from app.services.prompts.stages.chapter_planning import get_climax_instruction
    from app.services.workflow_context_builder import _extract_exact_chapter_outline
    from app.api.v1.workflow.routes_chapter import _build_chapter_plan_user_prompt

    bundle = _run_full_expansion(monkeypatch)
    expanded_outline = bundle["result"]["plot_outline"]

    def outline_of(n):
        text = _extract_exact_chapter_outline(expanded_outline, n)
        assert text, f"扩展后大纲缺少第{n}章细纲"
        return text

    # 第32章（卷末收官，标注"卷末收束·爆爽"）：32 不是 5 的倍数，旧取模逻辑给空；
    # 新逻辑按大纲标注给"大高潮" —— 行为改变的直接证据
    ch32 = get_climax_instruction(32, chapter_outline=outline_of(32))
    assert "大高潮" in ch32 and "按大纲节奏" in ch32, ch32

    # 第48章（本轮新增，爽点类型：爆爽）：48 不是 5 的倍数，旧逻辑同样给空
    ch48 = get_climax_instruction(48, chapter_outline=outline_of(48))
    assert "大高潮" in ch48, ch48

    # 第23章（阵前叫阵，标注小爽）：23 不是 5 的倍数，旧逻辑给空 → 新逻辑给小高潮
    ch23 = get_climax_instruction(23, chapter_outline=outline_of(23))
    assert "小高潮" in ch23, ch23

    # 第5章（玄甲巡边，无节奏标注）→ 空指令（不注入硬性节奏）
    assert get_climax_instruction(5, chapter_outline=outline_of(5)) == ""

    # 新增无标注章（第45章浊星天谕）：同样不注入硬性指令
    assert get_climax_instruction(45, chapter_outline=outline_of(45)) == ""

    # 无细纲时取模兜底仍可用，且声明"以大纲为准"
    fallback_major = get_climax_instruction(25)
    assert "经验节奏" in fallback_major and "以大纲为准" in fallback_major

    # --- 章节规划 prompt 集成：高潮指示按 routes_chapter 实际接线方式注入 ---
    plan_prompt = _build_chapter_plan_user_prompt(
        next_chapter_number=48,
        concept="凡人逆天改命",
        current_chapter_outline=outline_of(48),
        current_volume_context="卷三（33-48）秘辛揭开→遗局终章",
        core_character_anchor_context="林昭：查清观星台覆灭真相",
        focus_character_relationship_context="林昭-洛清霜：联手反杀中的相互提防",
        planning_character_context="林昭、洛清霜、慕容太后、阿蛮",
        epic_framework_context="",
        optimized_context_text="卷三收官，第二局开启",
        structured_memory_text="",
        previous_chapters_summary="第41-47章：终局前夜→盲棋入局→阵前倒戈",
        recent_chapter_assets_summary="",
        previous_ending="第二局的赌注，是整个九霄",
        climax_instruction=ch48,
    )
    assert "大高潮章节" in plan_prompt, "高潮指示未注入章节规划 prompt"
    assert "第48章" in plan_prompt


# ============================================================================
# 测试 3：delta 分批保护 —— count > 4 拆批 + 批间摘要注入 + 独立预算入口
# ============================================================================

def test_delta_chapter_batch_split_and_inter_batch_summary():
    from app.services.story_expansion_coord_pkg._standalone import OutlineBlock

    # 拆批纯函数：6 → [3,3]（均衡），5 → [3,2]，8 → [4,4]，≤4 不拆
    assert StoryExpansionCoordinator._split_delta_chapter_batches(6) == [3, 3]
    assert StoryExpansionCoordinator._split_delta_chapter_batches(5) == [3, 2]
    assert StoryExpansionCoordinator._split_delta_chapter_batches(8) == [4, 4]
    assert StoryExpansionCoordinator._split_delta_chapter_batches(4) == [4]
    assert StoryExpansionCoordinator._split_delta_chapter_batches(1) == [1]

    calls = []

    class BatchScriptedCoordinator(StoryExpansionCoordinator):
        def _configure_story_expansion_runtime_models(self, *args, **kwargs):
            return None

        def _invoke_chapter_json(self, prompt, fallback=None, chapter_count=1, **kwargs):
            calls.append({"prompt": prompt, "chapter_count": chapter_count})
            # 每批返回 batch_size 章，标题带批次标记便于断言
            if len(calls) == 1:
                titles = ["首批钩子章", "首批冲突章", "首批反转章"]
            else:
                titles = ["次批承接章", "次批升级章", "次批收束章"]
            return {
                "chapters": [
                    {
                        "title": t,
                        "scene_goal": "目标",
                        "conflict_design": "冲突",
                        "key_events": "事件",
                        "involved_characters": ["陆沉"],
                        "character_progress": "推进",
                        "plot_function": "作用",
                        "ending_hook": f"{t}的钩子",
                        "highlight_type": "爽点",
                        "foreshadowing_item": "伏笔",
                    }
                    for t in titles
                ]
            }

        def _invoke_text(self, prompt, **kwargs):
            return ""

        def _invoke_json(self, prompt, fallback=None):
            return dict(fallback or {})

    coord = BatchScriptedCoordinator(project_id=999998, genre="修真", planned_chapters_max=48)
    blocks = [
        OutlineBlock(original_number=n, title=f"存量第{n}章", body=f"第{n}章正文")
        for n in range(1, 6)
    ]
    new_blocks, raw_text = coord._generate_new_chapters_for_op(
        op={"action": "append", "after_chapter": 5, "count": 6, "goal": "推进黑市线"},
        blocks=blocks,
        world_setting="测试世界观",
        characters_text="陆沉：主角",
        new_character_cards="",
    )

    # 6 章拆成 2 批，每批按批大小传入预算参数
    assert len(calls) == 2, f"应拆 2 批，实际 {len(calls)} 批"
    assert [c["chapter_count"] for c in calls] == [3, 3]

    # 第 2 批 prompt 注入第 1 批摘要（承接前批、禁止复述）
    second_prompt = calls[1]["prompt"]
    assert "【同轮前批已生成章节】" in second_prompt, "批间摘要未注入第 2 批 prompt"
    assert "首批钩子章" in second_prompt, "第 1 批标题未进入批间摘要"
    assert "2/2" in second_prompt, "批次序号未标注"
    # 第 1 批 prompt 标注首批身份并要求留升级空间
    assert "1/2" in calls[0]["prompt"] and "首批" in calls[0]["prompt"]

    # 两批共 6 章全部收集渲染
    assert len(new_blocks) == 6, f"应收集 6 章，实际 {len(new_blocks)}"
    joined = "\n".join(getattr(b, "title", "") for b in new_blocks)
    for t in ("首批钩子章", "次批承接章", "次批收束章"):
        assert t in joined, f"缺少章节：{t}"
    assert "次批承接章的钩子" in raw_text, "结构化渲染缺少第 2 批内容"


def test_salvage_truncated_chapter_json():
    """思考模型挤占预算导致 JSON 尾部截断时，应回收完整章节卡而非整批丢弃。"""
    salvage = StoryExpansionCoordinator._salvage_truncated_chapter_json

    # 真实故障样本形态：第 3 章卡写到一半被截断
    truncated = (
        '{\n  "chapters": [\n    {\n      "title": "血契铜牌，黑市立契",\n'
        '      "scene_goal": "解析遗物血契",\n      "conflict_design": "胁迫合作",\n'
        '      "key_events": "立契",\n      "involved_characters": ["陆沉"],\n'
        '      "character_progress": "掌握主动",\n      "plot_function": "承接",\n'
        '      "ending_hook": "铜牌异动",\n      "highlight_type": "清算",\n'
        '      "foreshadowing_item": "血池旧契"\n    },\n'
        '    {\n      "title": "代位追偿，反噬立契",\n      "scene_goal": "反噬",\n'
        '      "conflict_design": "代价",\n      "key_events": "反噬",\n'
        '      "involved_characters": ["陆沉", "王长生"],\n      "character_progress": "代价显现",\n'
        '      "plot_function": "升级",\n      "ending_hook": "账簿翻页",\n'
        '      "highlight_type": "反噬",\n      "foreshadowing_item": "命灯即债主"\n    },\n'
        '    {\n      "title": "清算赵铁山，债契显形",\n      "character_progress": "苏清婉惊觉自己的命灯'
    )
    salvaged = salvage(truncated)
    assert salvaged and len(salvaged["chapters"]) == 2, "应抢救回收前 2 章完整章节卡"
    assert salvaged["chapters"][0]["title"] == "血契铜牌，黑市立契"
    assert salvaged["chapters"][1]["foreshadowing_item"] == "命灯即债主"

    # 边界：无 chapters 数组 / 空文本 / 完整 JSON 均不应误报
    assert salvage("") is None
    assert salvage("随便一段话") is None
    assert salvage('{"chapters": []}') is None

    # 字符串内花括号不应破坏括号配对
    tricky = '{"chapters": [{"title": "含{花括号}的标题", "scene_goal": "值"}, {"title": "第二'
    result = salvage(tricky)
    assert result and len(result["chapters"]) == 1
    assert result["chapters"][0]["title"] == "含{花括号}的标题"


def test_character_plot_validator_parse_variants():
    """LLM 对齐验证器解析应容忍模型输出格式变体（冒号/粗体/编号标题/圆点列表）。

    背景：deepseek-pro 实测输出 '**总分** **:** **78分**' 与 '## 1. 冗余人物'，
    旧正则要求 '总分：' 紧邻冒号且标题为纯 '## 冗余人物'，导致 score 丢失为 0、
    sections 漏提取，闸门误判（score=0 < 50 恒触发）。
    """
    from app.services.agents.character_plot_validator import CharacterPlotValidator

    validator = object.__new__(CharacterPlotValidator)
    parse = validator._parse_validation_result

    # 变体1：标准格式
    standard = (
        "## 匹配度评分\n总分：85/100\n\n## 冗余人物\n- 人物A：原因x\n- 人物B：原因y\n\n"
        "## 缺失人物\n- 角色类型C：需要理由\n\n## 关系合理性问题\n- 问题1：xxx\n\n## 改进建议\n1. 建议1\n"
    )
    r1 = parse(standard)
    assert r1["score"] == 85
    assert len(r1["redundant_characters"]) == 2
    assert len(r1["missing_characters"]) == 1
    assert len(r1["relationship_issues"]) == 1

    # 变体2：粗体总分 + 编号标题 + 圆点列表（真实故障样本形态）
    bold = (
        "## 匹配度评分\n**总分** **:** **78分**\n\n## 1. 冗余人物\n- 夜枭：游离主线\n\n"
        "## 2. 缺失人物\n• 皇子反派：增强张力\n\n## 3. 关系合理性问题\n- 倒戈太快\n"
    )
    r2 = parse(bold)
    assert r2["score"] == 78, f"粗体总分应被提取: {r2['score']}"
    assert r2["redundant_characters"] == ["夜枭：游离主线"]
    assert r2["missing_characters"] == ["皇子反派：增强张力"]
    assert r2["relationship_issues"] == ["倒戈太快"]

    # 变体3：无总分行 → score 保持 0，sections 仍可提取
    r3 = parse("## 冗余人物\n- 人物A\n\n## 缺失人物\n\n## 关系合理性问题\n- 问题x\n")
    assert r3["score"] == 0
    assert len(r3["relationship_issues"]) == 1

    # 变体4：异常高分截断到 100
    r4 = parse("总分：999\n## 冗余人物\n- a")
    assert r4["score"] == 100


# ============================================================================
# 测试 6：情节级问题 → deferred 结构债（跳过注定失败的复验）
# ============================================================================

def _make_gate_validation(score: int, issues: int = 0):
    return {
        "success": True,
        "score": score,
        "redundant_characters": ["墨七：游离主线"] * (1 if issues else 0),
        "missing_characters": [],
        "relationship_issues": ["关系问题x"] * max(0, issues - 1),
        "suggestions": [],
    }


def test_alignment_gate_defers_plot_level_issues():
    """修复器判定全部为情节级问题时：转 deferred + 写结构债，不浪费复验调用。"""
    coord = StoryExpansionCoordinator(project_id=999999)
    recheck_calls = []
    coord._run_character_plot_alignment_validation = lambda **kwargs: (
        recheck_calls.append(1),
        _make_gate_validation(80),
    )[1]
    coord._generate_alignment_repair_patch = lambda **kwargs: {
        "missing_character_cards": [],
        "chapter_duty_patches": [],
        "relationship_patches": [],
        "plot_level_issues": ["苏婉儿弧光需要跨多章主动行动线", "萧铁衣倒戈缺少渐进铺垫"],
    }
    result = {
        "plot_outline": "第1章：开局",
        "characters": "### 【姓名】：林昭",
        "character_relationships": "",
    }
    out = coord._apply_alignment_gate(
        result,
        _make_gate_validation(score=40, issues=3),
        characters="### 【姓名】：林昭",
        world_setting="世界",
    )
    assert out["alignment_gate_status"] == "deferred"
    assert "苏婉儿弧光" in out["alignment_structural_debt"]
    assert "萧铁衣倒戈" in out["alignment_structural_debt"]
    assert out["alignment_gate_retry"]["plot_level_issues"], "deferred 应记录情节级问题清单"
    # 关键：跳过复验（注记补丁未应用，复验必然与首验相同）
    assert recheck_calls == [], "deferred 路径不应触发复验调用"


def test_alignment_gate_mixed_issues_records_debt_after_recheck():
    """注记级补丁 + 情节级问题混合：走正常补丁→复验流程，结构债仍记录。"""
    coord = StoryExpansionCoordinator(project_id=999999)
    recheck_calls = []
    coord._run_character_plot_alignment_validation = lambda **kwargs: (
        recheck_calls.append(1),
        _make_gate_validation(80),
    )[1]
    coord._generate_alignment_repair_patch = lambda **kwargs: {
        "missing_character_cards": [],
        "chapter_duty_patches": [
            {"chapter_marker": "第1章", "character": "墨七", "duty": "暗线推进情报交易"}
        ],
        "relationship_patches": [],
        "plot_level_issues": ["苏婉儿弧光需要跨多章主动行动线"],
    }
    result = {
        "plot_outline": "第1章：开局\n原有内容行",
        "characters": "### 【姓名】：林昭",
        "character_relationships": "",
    }
    out = coord._apply_alignment_gate(
        result,
        _make_gate_validation(score=40, issues=3),
        characters="### 【姓名】：林昭",
        world_setting="世界",
    )
    # 复验通过 → repaired，但情节级债仍记录供下轮承接
    assert out["alignment_gate_status"] == "repaired"
    assert len(recheck_calls) == 1
    assert "苏婉儿弧光" in out["alignment_structural_debt"]
    # 注记补丁已应用
    assert "人物职责补充：墨七" in out["plot_outline"]


def test_alignment_gate_passed_clears_debt():
    """首验通过 → passed 且结构债显式清空（调用方以最新状态覆盖存储）。"""
    coord = StoryExpansionCoordinator(project_id=999999)
    out = coord._apply_alignment_gate(
        {"plot_outline": "第1章：x", "characters": "", "character_relationships": ""},
        _make_gate_validation(score=80),
        characters="",
        world_setting="世界",
    )
    assert out["alignment_gate_status"] == "passed"
    assert out["alignment_structural_debt"] == ""


def test_alignment_gate_empty_patch_falls_back_to_debt():
    """修复器全空输出（真实环境观察到）：首验问题清单整体转结构债，仍可下轮承接。"""
    coord = StoryExpansionCoordinator(project_id=999999)
    recheck_calls = []
    coord._run_character_plot_alignment_validation = lambda **kwargs: (
        recheck_calls.append(1),
        _make_gate_validation(80),
    )[1]
    coord._generate_alignment_repair_patch = lambda **kwargs: {
        "missing_character_cards": [],
        "chapter_duty_patches": [],
        "relationship_patches": [],
        "plot_level_issues": [],
    }
    out = coord._apply_alignment_gate(
        {"plot_outline": "第1章：开局", "characters": "### 【姓名】：林昭", "character_relationships": ""},
        _make_gate_validation(score=40, issues=3),
        characters="### 【姓名】：林昭",
        world_setting="世界",
    )
    assert out["alignment_gate_status"] == "deferred"
    assert "墨七" in out["alignment_structural_debt"], "首验问题清单应整体转为结构债"
    assert recheck_calls == []


# ============================================================================
# 测试 7：结构债与人物戏份约束注入章节生成 prompt（跨轮修复 + 生成时预防）
# ============================================================================

def test_delta_prompt_injects_structural_debt_and_presence():
    """无章节大纲分支：结构债与人物覆盖约束进入每批 prompt；批间注入零出场补戏提示。"""

    class BatchCaptureCoordinator(ScriptedCoordinator):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.chapter_prompts = []

        def _invoke_chapter_json(self, prompt, fallback=None, **kwargs):
            self.chapter_prompts.append(prompt)
            return {
                "chapters": [
                    {
                        "title": f"批次{len(self.chapter_prompts)}测试章{i}",
                        "scene_goal": "目标",
                        "conflict_design": "①冲突 → ②升级 → ③反转",
                        "key_events": "事件",
                        "involved_characters": ["林昭"],
                        "character_progress": "推进",
                        "plot_function": "作用",
                        "ending_hook": "钩子",
                        "highlight_type": "",
                        "foreshadowing_item": "伏笔",
                    }
                    for i in range(3)
                ]
            }

    coord = BatchCaptureCoordinator(project_id=999999, genre="修真", planned_chapters_max=50)
    coord._alignment_structural_debt = "- 苏婉儿弧光需要跨多章主动行动线"
    result = coord.generate_outline_delta(
        current_outline="总纲：无显式章节标题的叙述性大纲文本。",
        characters_text=CHARACTERS,
        world_setting=WORLD_SETTING,
        plan={"chapters_needed": 6, "characters_needed": 0},
        new_character_cards="",
    )
    # 6 章拆 2 批（3+3）
    assert len(coord.chapter_prompts) == 2
    first_prompt, second_prompt = coord.chapter_prompts

    # 结构债 + 人物覆盖约束注入每批 prompt
    for prompt in (first_prompt, second_prompt):
        assert "上轮遗留结构债" in prompt, "结构债应注入章节生成 prompt"
        assert "苏婉儿弧光" in prompt
        assert "人物覆盖约束" in prompt

    # 第一批章节只写林昭 → CHARACTERS 中其他人物零出场 → 第二批 prompt 应含补戏提示
    assert "零出场人物" in second_prompt, "批间应注入零出场人物补戏提示"
    assert "零出场人物" not in first_prompt

    # 章节产物完整（2 批 × 3 章）
    assert "批次1测试章0" in result["plot_outline"]
    assert "批次2测试章2" in result["plot_outline"]
