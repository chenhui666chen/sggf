"""
结构设计阶段提示词模块

负责情节大纲（卷结构）的生成
"""

from typing import Optional
from dataclasses import dataclass

from app.services.prompts.genre_registry import (
    get_genre_rhythm_guide as _get_genre_rhythm_guide,
    resolve_genre,
)


@dataclass
class StructureDesignPrompts:
    """结构设计提示词集合（情节大纲生成）"""
    
    # 版本信息
    version: str = "1.0.0"
    
    @staticmethod
    def get_structure_prompt(
        genre_rhythm_guide: str = "",
        genre: str = "通用"
    ) -> str:
        """
        获取结构设计（情节大纲）的 user prompt（纯引用式，避免信息冗余）
        
        Args:
            genre_rhythm_guide: 题材专属节奏指导
            genre: 题材类型（用于任务描述）
        
        Returns:
            完整的结构设计 user prompt
        
        注意：
            - 本方法不再接收concept/world_setting/characters参数
            - 所有详细信息通过context中的optimized_context传递
            - 避免分层摘要与手动截断共存造成信息冲突
        """
        base_prompt = f'''你是一名擅长网文结构的"情节架构师"，需要基于context中提供的完整故事信息，规划一部{genre}题材长篇网文的【情节大纲】。

【重要说明】
context中的optimized_context字段包含了经过AI优化的完整信息，其中涵盖：
- 故事概念的核心骨架和关键情节片段
- 世界观设定的核心要素和详细规则
- 主要人物的设定骨架和详细背景

请仔细阅读context中的所有信息，确保大纲设计与背景设定完全一致

【总体要求】
1. 采用"按卷/阶段 + 起承转合骨架 + 网文爽点节奏"的混合结构。
2. 每一卷/阶段都要明确：阶段目标、主要矛盾、爆点与升级节点。
3. 不写细节对白，只写"发生什么事 + 冲突方向 + 爽点类型"。
4. 确保与context中的世界观规则、人物性格、故事主线保持一致。

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
    获取题材专属节奏指导（委托给 genre_registry）
    
    Args:
        genre: 题材名称
    
    Returns:
        题材专属节奏指导文本
    """
    return _get_genre_rhythm_guide(genre)


# 快捷构建函数（保持向后兼容，但已弃用）
def build_structure_design_prompt(
    concept: str = "",  # 已弃用，仅为向后兼容保留
    world_setting: str = "",  # 已弃用，仅为向后兼容保留
    characters: str = "",  # 已弃用，仅为向后兼容保留
    genre: str = "",
    genre_module: Optional[dict] = None
) -> str:
    """
    构建结构设计提示词的快捷函数
    
    警告：本函数已弃用。请直接使用 StructureDesignPrompts.get_structure_prompt()
    concept/world_setting/characters 参数已不再使用，所有信息通过 context 传递。
    
    Args:
        concept: (已弃用) 故事概念
        world_setting: (已弃用) 世界观设定
        characters: (已弃用) 人物设定
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
        genre_rhythm_guide=rhythm_guide,
        genre=genre or "通用"
    )
