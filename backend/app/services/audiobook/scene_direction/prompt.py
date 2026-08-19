"""Seed 专用改编 Prompt（指导文档 §6）。

与 legacy_stems 输出合同彻底分离：不包含分轨参数、素材 ID、混音覆盖率等
旧合同内容，只要求输出 §5 定义的结构化导演计划（严格 JSON）。
合同文本或 schema 变化必须提升合同版本，director_prompt_hash /
director_schema_hash 进入 DirectorInputSignature。
"""

from __future__ import annotations

from typing import Dict, List

from ..hashing import canonical_hash

SEED_DIRECTOR_PROMPT_CONTRACT_NAME = "seed_scene_director_prompt"
SEED_DIRECTOR_PROMPT_CONTRACT_VERSION = "1.0.0"
SEED_DIRECTOR_SCHEMA_CONTRACT_NAME = "seed_scene_director_schema"
SEED_DIRECTOR_SCHEMA_CONTRACT_VERSION = "1.0.0"

SEED_DIRECTOR_PROMPT_TEMPLATE = """\
你是有声书声音场景导演。请基于已审定的剧本片段输出结构化导演计划。

改编目标（按顺序执行）：
1. 先识别连续场景和真实转场。
2. 提取时间、地点、空间声学、持续环境和整体情绪过程。
3. 保持审定台词与说话人不变；台词文本由系统按片段索引读取，你不需要也不得回显台词内容。
4. 标记前景、背景、重叠和插话关系。
5. 把非语言人声（笑、哭、吸气、喘息、无词惊呼）与可辨识语言分离。
6. 把音效蒙太奇按顺序分组。
7. 描述音乐进入、变化、降低、停止和延续的生命周期。
8. 标记电话、远端、混响、移动等声学处理。
9. 标记不可切断的问答、因果动作和情绪弧。
10. 不得新增：不为增强戏剧性新增原文不存在的台词、人物行动或具体物件。

事实约束：
- 每个有台词的片段必须且只能被一个 speech 事件消费，不遗漏、不重复、不重排。
- 非语言人声必须附带证据（原文片段字段子串或已审定分析 finding），禁止自证。
- 重叠与背景插话必须显式引用相对片段索引。

输出格式：只输出严格 JSON，根对象为 {{"scenes": [...]}}，字段结构见 schema 说明。
"""

SEED_DIRECTOR_SCHEMA_DESCRIPTION = {
    "root": {"scenes": "SeedSceneDirection[]"},
    "scene_fields": (
        "scene_key",
        "source_segment_indices",
        "context",
        "speech",
        "vocalizations",
        "sounds",
        "timeline_mode",
        "target_duration_s",
    ),
    "context_fields": (
        "time",
        "location",
        "acoustic_space",
        "ambient_state",
        "emotional_arc",
        "story_beat",
        "carry_in",
        "carry_out",
    ),
    "speech_fields": (
        "source_segment_index",
        "speaker",
        "layer(foreground|background)",
        "anchor(sequence|before|during|after|overlap)",
        "relative_to_segment_index",
        "performance",
        "acoustic",
        "verification_policy(hard|soft|semantic_only)",
        "start_s",
        "end_s",
    ),
    "vocalization_fields": (
        "speaker",
        "description",
        "anchor(before|during|after|overlap)",
        "relative_to_segment_index",
        "evidence(segment|reviewed_analysis 判别联合)",
        "layer",
        "performance",
        "acoustic",
        "provenance(explicit|inferred_performance)",
    ),
    "sound_fields": (
        "kind(sfx|ambient|music|transition)",
        "description",
        "anchor(before|during|after|throughout|until_text|overlap)",
        "relative_to_segment_index",
        "related_text",
        "duration_s",
        "delay_s",
        "layer",
        "sequence_group",
    ),
}


def build_seed_director_prompt(
    segments_text: str,
    *,
    chapter_context: str = "",
    character_profiles_text: str = "",
    capability_block: str = "",
) -> List[Dict[str, str]]:
    """构造导演调用的 messages；segments_text 为已审定片段的确定性行式表示。"""
    context_block = f"章节上下文：{chapter_context}\n" if chapter_context else ""
    profiles_block = f"角色档案：{character_profiles_text}\n" if character_profiles_text else ""
    capability = f"{capability_block}\n" if capability_block else ""
    user_content = (
        f"{capability}{context_block}{profiles_block}"
        f"已审定剧本片段（索引|说话人|台词，台词仅供定位，不得改写）：\n{segments_text}"
    )
    return [
        {"role": "system", "content": SEED_DIRECTOR_PROMPT_TEMPLATE},
        {"role": "user", "content": user_content},
    ]


def director_prompt_hash() -> str:
    """导演 Prompt 合同哈希；模板或版本变化即变化（§12.2 输入签名字段）。"""
    return canonical_hash(
        SEED_DIRECTOR_PROMPT_TEMPLATE,
        contract_name=SEED_DIRECTOR_PROMPT_CONTRACT_NAME,
        contract_version=SEED_DIRECTOR_PROMPT_CONTRACT_VERSION,
    )


def director_schema_hash() -> str:
    """导演输出 schema 合同哈希；schema 变化即变化。"""
    return canonical_hash(
        SEED_DIRECTOR_SCHEMA_DESCRIPTION,
        contract_name=SEED_DIRECTOR_SCHEMA_CONTRACT_NAME,
        contract_version=SEED_DIRECTOR_SCHEMA_CONTRACT_VERSION,
    )


__all__ = [
    "SEED_DIRECTOR_PROMPT_CONTRACT_VERSION",
    "SEED_DIRECTOR_PROMPT_TEMPLATE",
    "SEED_DIRECTOR_SCHEMA_CONTRACT_VERSION",
    "SEED_DIRECTOR_SCHEMA_DESCRIPTION",
    "build_seed_director_prompt",
    "director_prompt_hash",
    "director_schema_hash",
]
