from __future__ import annotations

from app.services.audiobook.project_audio_config import get_audio_engine_mode


def normalize_script_audio_engine_mode(value: str | None) -> str:
    return get_audio_engine_mode({"audio_engine_mode": value})


def build_script_analysis_engine_guidance(value: str | None) -> str:
    mode = normalize_script_audio_engine_mode(value)
    if mode == "seed_scene":
        return """**当前音频引擎：豆包 Seed Audio 场景生成（seed_scene）**
- 分析时以完整声音场景为单位，识别空间、持续环境底音、音乐生命周期、动作与对白的穿插关系。
- 标出不应切断的连续表演、多人交错、非语言人声、电话/远近/回声等声学处理。
- 不规划本地素材、素材 ID 或分轨混音参数；后续会把剧本事实确定性编译为 Seed Audio 场景提示词。
"""
    return """**当前音频引擎：分轨合成（legacy_stems）**
- 分析时识别可独立合成的 TTS 单元、可单独生成或匹配的音效，以及可执行的配乐时间线。
- 标出音效触发点、持续时间、空间位置、淡入淡出和人声避让要求。
- 不依赖整场生成模型一次完成多人表演、动作音效和环境变化。
"""


def build_script_transform_engine_guidance(value: str | None) -> str:
    mode = normalize_script_audio_engine_mode(value)
    if mode == "seed_scene":
        return """**当前音频引擎：豆包 Seed Audio 场景生成（seed_scene）**
- 台词、说话人和剧情事实仍是唯一事实源；不要为场景模式改写或增补原文台词。
- instruct_scene 必须描述可持续的空间、环境底音和声学状态；同一场景连续片段保持一致，只在真实转场时更新。
- 动作、环境音和非语言人声必须明确发生在先于台词、伴随台词、随后发生或持续到场景结束中的哪个阶段。
- music_cue 描述音乐的进入、延续、变化、停止和主要乐器/情绪，不要只写笼统的“紧张配乐”。
- performance_notes 描述角色从起始到结束的情绪变化、语速、音量、重读、停顿及笑声/哭腔/吸气/喘息等微表演。
- 不要输出或依赖素材 asset_id、分轨音量曲线或本地文件；Seed Audio 根据自然语言场景描述生成全部声音。
- 不要把每句话机械切成独立场景；连续对白、动作和环境应保持可组合的场景连续性。
"""
    return """**当前音频引擎：分轨合成（legacy_stems）**
- 台词、说话人和剧情事实仍是唯一事实源；每个 TTS 片段都必须能够独立合成并保持上下文可理解。
- sound_effects 必须能够独立生成或匹配，使用明确的动作/环境声音名称，避免依赖整场模型理解含混指代。
- 对关键音效填写可执行的 volume、delay、fade_in、fade_out、duration、position_3d 和 timing。
- music_cue 应形成可执行的分轨时间线，明确风格、音量、起止、淡入淡出和对白避让。
- 复杂的句中多人交错、动作与台词重叠应拆成可定位事件，不得依赖整场模型一次完成。
"""


def build_script_review_engine_guidance(value: str | None) -> str:
    mode = normalize_script_audio_engine_mode(value)
    if mode == "seed_scene":
        return """Seed Audio 场景生成审稿：
- 检查 instruct_scene 中环境与空间状态是否连续；同一地点不要无故漂移，真实转场必须明确。
- 检查动作、环境音、音乐和非语言人声是否写清先于、伴随、随后、持续等相对时序。
- 检查音乐是否说明进入、变化、停止，复杂表演是否保留情绪过程与微表演。
- Seed 渲染不得依赖素材 asset_id、本地文件或精确分轨混音参数；输入中已有的 asset_id 原样保留供局部回退使用，但不把它编入 Seed Prompt。
- 不要为了凑场景效果新增台词、人物动作或原文不存在的声音事实。
"""
    return """分轨合成审稿：
- 检查每个 TTS 片段是否能够独立朗读且上下文可理解。
- 检查每个音效是否可独立生成或匹配，并有清晰触发位置。
- 对关键音效和配乐检查 volume、delay、fade_in、fade_out、duration 与时间线是否可执行。
- 句中复杂重叠事件应拆成可定位的独立事件，不得依赖整场生成能力。
"""


__all__ = [
    "build_script_analysis_engine_guidance",
    "build_script_review_engine_guidance",
    "build_script_transform_engine_guidance",
    "normalize_script_audio_engine_mode",
]
