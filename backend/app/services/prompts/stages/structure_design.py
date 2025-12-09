"""
结构设计阶段提示词模块

负责情节大纲（卷结构）的生成
"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class StructureDesignPrompts:
    """结构设计提示词集合（情节大纲生成）"""
    
    # 版本信息
    version: str = "1.0.0"
    
    @staticmethod
    def get_structure_prompt(
        concept: str,
        world_setting: str,
        characters: str,
        genre_rhythm_guide: str = ""
    ) -> str:
        """
        获取结构设计（情节大纲）的 user prompt
        
        Args:
            concept: 故事概念（截断至500字）
            world_setting: 世界观设定（截断至300字）
            characters: 人物设定（截断至300字）
            genre_rhythm_guide: 题材专属节奏指导
        
        Returns:
            完整的结构设计 user prompt
        """
        base_prompt = f'''你是一名擅长网文结构的"情节架构师"，需要在已有【故事概念 + 世界观设定 + 主要人物】的基础上，规划一部长篇网文的【情节大纲】。

【故事概念】
{concept}

【世界观设定】
{world_setting}

【主要人物】
{characters}

【总体要求】
1. 采用"按卷/阶段 + 起承转合骨架 + 网文爽点节奏"的混合结构。
2. 每一卷/阶段都要明确：阶段目标、主要矛盾、爆点与升级节点。
3. 不写细节对白，只写"发生什么事 + 冲突方向 + 爽点类型"。

请按以下结构输出：

1. **总体结构概览**
- 用 3–5 行概括全书走向（例如：底层生存 → 技术崛起 → 撼动旧秩序 → 新范式成型）；
- 标明本书更偏"爽文逆袭""权谋智斗""悬疑走向""慢热成长"等（可组合）；
- 明确整体"情绪起伏节奏"，例如："小爽 → 压抑 → 中爽 → 再压抑 → 爆爽 → 余韵"，避免全程同强度爽点导致疲劳。

2. **卷一：XXXX（起）**
- **阶段目标**：主角要达成的阶段性目标（例如：活下来、保住家人、摆脱债务、进入学院等）；
- **核心矛盾**：这一卷持续的主要矛盾；
- **关键节点建议**（建议 4–8 个），每个节点必须包含：
  - 场景（简短描述发生在哪里）；
  - 冲突（谁 vs 谁，矛盾点是什么）；
  - 爽点/转折：说明这是"打脸、越级、技术降维打击、关系反转、真相片段"等哪一类爽点；
  - **爽点强度：小爽 / 中爽 / 爆爽**（必须标注）；
  - 建议章节范围（如"第1–3章""第4–6章"），可参考"约每3章一个小高潮"的节奏（例如：第3章、第6章设小爽点，第10章左右设卷内爆点）。

3. **卷二：XXXX（承）**
- 同卷一格式：阶段目标 + 核心矛盾 + 关键节点列表；
- 注意承接卷一的未解矛盾，并引入新的升级点（更大格局、更强对手或更深真相）。

4. **卷三：XXXX（转）**
- 侧重重大转折与价值观/世界观层面的冲突升级，可以有一段"压抑期"，为后续爆爽做铺垫。

5. **卷四：XXXX（合）**（或后续多卷）
- 交代主线收束方式，安排终极爆点与情绪"余韵"。

【节奏与爽点规则】
- 保证每 5–10 章至少有一个明确爽点（反杀、升级、打脸、关系反转、真相片段等）；
- 在每卷内，爽点强度建议遵循"小爽 → 中爽 → 小缓冲 → 爆爽"的节奏结构；
- 不要在前期一次性暴露所有终极秘密，要保留后续升级与反转空间；
- 若是系统流/科技流，每卷引入一个新的"工具/规则应用方式"，形成能力或玩法上的升级感。

请根据以上要求输出完整的卷结构大纲。{genre_rhythm_guide}'''
        
        return base_prompt


def get_genre_rhythm_guide(genre: str) -> str:
    """
    获取题材专属节奏指导
    
    Args:
        genre: 题材名称
    
    Returns:
        题材专属节奏指导文本
    """
    # 从 GENRE_PROMPT_MODULES 获取，这里提供备用映射
    GENRE_RHYTHM_GUIDES = {
        "修仙": """
【修仙题材节奏指导】
- 境界突破节奏：每5-8章设置一个小突破（如灵力精纯、招式领悟），每15-20章设置一个大境界突破
- 宗门任务/秘境探索作为经验积累的主要载体
- 适当加入"丹药炼制""法宝祭炼"等成长辅线
- 境界压制与越级战斗交替出现，保持张力""",

        "玄幻": """
【玄幻题材节奏指导】
- 血脉觉醒/传承获得作为核心爽点
- 每卷安排1-2次"越级挑战"，展现天赋碾压
- 家族/势力争斗作为外部压力源
- 神器/血脉等级提升与实战能力提升同步""",

        "都市": """
【都市题材节奏指导】
- 商战节奏：每5章一个小项目/合同，每卷一个大交易
- 财富跨越：从百万到千万到亿级的清晰节点
- 打脸场景要有铺垫+围观+反应三要素
- 适当穿插情感线调节节奏""",

        "悬疑": """
【悬疑题材节奏指导】
- 线索布局：每章埋1-2个小线索，每卷揭示1个大真相
- 反转节奏：每卷至少2个意外反转
- 气氛营造优先于动作场景
- 真相揭露采用"洋葱式"层层剥开""",

        "言情": """
【言情题材节奏指导】
- 甜宠/虐恋节奏交替
- 情感里程碑：初见→误会→心动→表白→在一起
- 每卷设置1-2个"甜蜜高光时刻"
- 第三者/家庭阻力作为外部压力源""",

        "耽美": """
【耽美题材节奏指导】
- 暧昧张力→试探→突破→确认的情感递进
- 每卷设置1个关系升级的关键场景
- 内心戏份与外部事件交织
- 符合平台尺度，注重情感深度""",

        "科幻": """
【科幻题材节奏指导】
- 科技突破作为核心爽点
- 探索节奏：每卷发现1个新文明/新星域/新技术
- 人性思考与科幻设定融合
- 星际战斗节奏紧凑，注重战术呈现""",

        "纯文学": """
【纯文学题材节奏指导】
- 顿悟时刻作为情感高点
- 诗意表达与日常叙事交织
- 内心成长优先于外部事件
- 结局可留白，引发读者思考"""
    }
    
    return GENRE_RHYTHM_GUIDES.get(genre, "")


# 快捷构建函数
def build_structure_design_prompt(
    concept: str,
    world_setting: str,
    characters: str,
    genre: str = "",
    genre_module: Optional[dict] = None
) -> str:
    """
    构建结构设计提示词的快捷函数
    
    Args:
        concept: 故事概念
        world_setting: 世界观设定
        characters: 人物设定
        genre: 题材名称
        genre_module: 题材模块（可选，包含 outline_rhythm_guide）
    
    Returns:
        完整的结构设计 user prompt
    """
    # 获取题材专属节奏指导
    if genre_module and genre_module.get('outline_rhythm_guide'):
        rhythm_guide = genre_module['outline_rhythm_guide']
    else:
        rhythm_guide = get_genre_rhythm_guide(genre)
    
    return StructureDesignPrompts.get_structure_prompt(
        concept=concept[:500] if concept else '无',
        world_setting=world_setting[:300] if world_setting else '无',
        characters=characters[:300] if characters else '无',
        genre_rhythm_guide=rhythm_guide
    )
