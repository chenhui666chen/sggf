from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass, field

from agents.llm_client import (
    chat_completions,
    env_flag,
    extract_json_array,
    extract_json_object,
    llm_stream_context,
    resolve_llm_runtime_config,
)
from pipeline.style_presets import ensure_style_payload


@dataclass
class CharacterProfile:
    """角色档案 - 用于通义万相2.6角色一致性"""
    
    character_id: str
    name: str
    reference_video_path: str = ""
    reference_image_path: str = ""
    voice_reference_path: str = ""
    appearance_description: str = ""
    personality_traits: List[str] = field(default_factory=list)
    voice_style: str = "natural"
    voice_id: str = ""
    voice_profile_id: str = ""
    importance: str = "secondary"
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "character_id": self.character_id,
            "name": self.name,
            "reference_video_path": self.reference_video_path,
            "reference_image_path": self.reference_image_path,
            "voice_reference_path": self.voice_reference_path,
            "appearance_description": self.appearance_description,
            "personality_traits": self.personality_traits,
            "voice_style": self.voice_style,
            "voice_id": self.voice_id,
            "voice_profile_id": self.voice_profile_id,
            "importance": self.importance,
            "created_at": self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharacterProfile":
        """从字典创建角色档案"""
        return cls(
            character_id=data.get("character_id", ""),
            name=data.get("name", ""),
            reference_video_path=data.get("reference_video_path", ""),
            reference_image_path=data.get("reference_image_path", ""),
            voice_reference_path=data.get("voice_reference_path", ""),
            appearance_description=data.get("appearance_description", ""),
            personality_traits=data.get("personality_traits", []),
            voice_style=data.get("voice_style", "natural"),
            voice_id=data.get("voice_id", ""),
            voice_profile_id=data.get("voice_profile_id", ""),
            importance=data.get("importance", "secondary"),
            created_at=data.get("created_at", "")
        )


@dataclass
class AudioMarker:
    """音频标记 - 用于通义万相2.6声画同步"""
    
    scene_number: int
    character_name: str
    dialogue_line: str
    start_time: float = 0.0
    end_time: float = 0.0
    voice_style: str = "natural"
    emotion: str = "neutral"
    background_music: str = ""
    sound_effects: List[str] = field(default_factory=list)
    
    voice_tone: str = ""
    voice_speed: str = ""
    voice_color: str = ""
    voice_accent: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "scene_number": self.scene_number,
            "character_name": self.character_name,
            "dialogue_line": self.dialogue_line,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "voice_style": self.voice_style,
            "emotion": self.emotion,
            "background_music": self.background_music,
            "sound_effects": self.sound_effects,
            "voice_tone": self.voice_tone,
            "voice_speed": self.voice_speed,
            "voice_color": self.voice_color,
            "voice_accent": self.voice_accent
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioMarker":
        """从字典创建音频标记"""
        return cls(
            scene_number=data.get("scene_number", 0),
            character_name=data.get("character_name", ""),
            dialogue_line=data.get("dialogue_line", ""),
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
            voice_style=data.get("voice_style", "natural"),
            emotion=data.get("emotion", "neutral"),
            background_music=data.get("background_music", ""),
            sound_effects=data.get("sound_effects", []),
            voice_tone=data.get("voice_tone", ""),
            voice_speed=data.get("voice_speed", ""),
            voice_color=data.get("voice_color", ""),
            voice_accent=data.get("voice_accent", "")
        )
    
    def to_wanx_audio_description(self) -> str:
        """
        转换为阿里云百炼的声音描述格式
        
        返回格式：
        人声：角色说话的内容 + 情绪 + 语调 + 语速 + 音色 + 口音
        音效：音源材质 + 行为 + 环境音
        背景音乐：背景音乐/配乐 + 风格
        """
        parts = []
        
        if self.dialogue_line:
            voice_parts = [f"{self.character_name}说道：{self.dialogue_line}"]
            
            if self.emotion:
                emotion_map = {
                    "neutral": "平静",
                    "happy": "开心",
                    "sad": "悲伤",
                    "angry": "愤怒",
                    "fearful": "恐惧",
                    "surprised": "惊讶",
                    "tense": "紧张",
                    "calm": "温和",
                    "excited": "兴奋"
                }
                voice_parts.append(f"语气{emotion_map.get(self.emotion, self.emotion)}")
            
            if self.voice_speed:
                speed_map = {
                    "slow": "缓慢",
                    "normal": "适中",
                    "fast": "急促",
                    "very_fast": "极快"
                }
                voice_parts.append(f"语速{speed_map.get(self.voice_speed, self.voice_speed)}")
            
            if self.voice_tone:
                voice_parts.append(self.voice_tone)
            
            if self.voice_color:
                voice_parts.append(f"声音{self.voice_color}")
            
            if self.voice_accent:
                voice_parts.append(f"{self.voice_accent}口音")
            
            parts.append("人声：" + "，".join(voice_parts))
        
        if self.sound_effects:
            for effect in self.sound_effects:
                parts.append(f"音效：{effect}")
        
        if self.background_music:
            parts.append(f"背景音乐：{self.background_music}")
        
        return "；".join(parts) if parts else ""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


def _should_enable_script_enhance(*, payload: Dict[str, Any]) -> bool:
    override = payload.get("script_enhance")
    if override is not None:
        return bool(override)
    override = payload.get("script_enhancement_enabled")
    if override is not None:
        return bool(override)
    quality_mode = str(payload.get("quality_mode") or "").strip().lower()
    default_enabled = quality_mode == "quality"
    return env_flag("DREAMWEAVER_SCRIPT_ENHANCE", default=default_enabled)


def _format_llm_error(exc: Exception) -> str:
    msg = f"{exc.__class__.__name__}: {exc}"
    msg = re.sub(r"\s+", " ", msg).strip()
    if len(msg) > 260:
        msg = msg[:260] + "…"
    return msg


def _pick_dreamweaver_script_model() -> str:
    model = (os.getenv("DREAMWEAVER_SCRIPT_MODEL") or "").strip()
    if model:
        return model

    # 兼容历史：部分部署把 DEEPSEEK_MODEL 指向 qwen-*，继续允许该路径复用百炼通道。
    # DeepSeek V4 模型由 resolve_llm_runtime_config 统一切到官方 DeepSeek API。
    legacy = (os.getenv("DEEPSEEK_MODEL") or "").strip()
    if legacy.startswith("qwen") or legacy in {"deepseek-v4-flash", "deepseek-v4-pro"}:
        return legacy

    return "qwen-plus"


def _pick_dreamweaver_script_enhance_model() -> str:
    """
    剧本二次润色模型选择：
    - 优先 DREAMWEAVER_SCRIPT_ENHANCE_MODEL
    - 其次复用 DREAMWEAVER_SCRIPT_MODEL（或其 legacy qwen*）
    """
    model = (os.getenv("DREAMWEAVER_SCRIPT_ENHANCE_MODEL") or "").strip()
    if model:
        return model
    return _pick_dreamweaver_script_model()


def _llm_enhance_script(
    ctx: Any,
    *,
    source_text: str,
    script_text: str,
    entities: Dict[str, Any],
    style_prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    temperature: float,
    max_scenes: int,
    estimated_scenes: int = 1,
    quality_mode: str = "standard",
) -> Tuple[str, Dict[str, Any]]:
    dialogue_range = _estimate_dialogue_range(
        source_text=source_text,
        quality_mode=quality_mode,
        estimated_scenes=estimated_scenes,
    )
    
    system = (
        "你是资深短剧编剧润色与连续性审校专家。\n"
        "任务：对【短剧剧本草稿】进行二次润色与一致性修复，输出更可拍、更适合分镜与后续多模态生成的版本。\n"
        "输出必须是严格 JSON（不要 Markdown 代码块、不要解释文字、不要多余字段）。"
    )

    user = (
        "请仅输出如下 JSON：\n"
        "{\n"
        '  "script_text": "Markdown 剧本草稿（保持原有分场数量与顺序不变；保留标题/概要/分场结构；每场必须包含人物/节拍/对白/视觉锚点）",\n'
        '  "entities": {\n'
        '    "characters": [{"name": "角色名", "descriptor": "外观+气质+关键特征", "importance": "主角|重要|次要|群像"}],\n'
        '    "scenes": [{"name": "场景名", "descriptor": "空间/氛围/时间/天气/风格"}],\n'
        '    "props": [{"name": "道具名", "descriptor": "材质/外观/用途/关键特征"}]\n'
        "  }\n"
        "}\n\n"
        "硬性约束（必须遵守）：\n"
        f"- 分场数量必须保持不变，且不超过 {max_scenes} 场\n"
        "- 不新增/删除/合并分场，不改变分场顺序\n"
        '- 概要：每条一行，格式为"- 场X：一句话摘要（<=40字）"，不得换行，不要包含"第X章/第一章"等章节标记\n'
        '- 每场人物行不得出现"按实际删改/待补全/占位/……"等占位词；人物必须来自 entities.characters\n'
        f"- 每场对白 {dialogue_range} 句，尽量短句对打（避免连续长独白/术语堆砌）\n"
        "- 每场节拍 2~4 条（动作/反应/推进），用于分镜拆解\n"
        "- 视觉锚点：要能为“角色一致性/场景一致性/道具一致性”提供可复用信息，但避免要求画面生成清晰文字/数字/图表\n"
        "- 不要出现水印、字幕、UI 文案等要求；不要出现镜头术语（如：切到/特写/推拉摇移/旁白格式）\n\n"
        f"目标风格（仅用于视觉锚点氛围，不要改写剧情设定）：{style_prompt}\n\n"
        "【章节文本】（用于校验人物/设定是否串台）：\n"
        f"{(source_text or '')[:12000]}\n\n"
        "【当前剧本草稿】（需要润色与修复）：\n"
        f"{(script_text or '')[:12000]}\n\n"
        "【当前实体抽取】（需要修复并与剧本一致）：\n"
        f"{str(entities)[:6000]}"
    )

    with llm_stream_context(ctx, stage="script", stream_key="script_enhance") as on_chunk:
        content = chat_completions(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            timeout_s=timeout_s,
            temperature=temperature,
            on_chunk=on_chunk,
        )
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        raise RuntimeError("invalid enhanced script JSON: missing object")
    script_candidate = obj.get("script_text")
    if not isinstance(script_candidate, str) or not script_candidate.strip():
        raise RuntimeError("invalid enhanced script JSON: missing script_text")
    candidate_script_text = _normalize_script_text(script_text=script_candidate)
    if not _is_script_text_valid(candidate_script_text):
        raise RuntimeError("invalid enhanced script_text: missing required sections/template markers")

    ent = obj.get("entities")
    out_entities: Dict[str, Any] = {"characters": [], "scenes": [], "props": []}
    if isinstance(ent, dict):
        out_entities = {
            "characters": ent.get("characters") if isinstance(ent.get("characters"), list) else [],
            "scenes": ent.get("scenes") if isinstance(ent.get("scenes"), list) else [],
            "props": ent.get("props") if isinstance(ent.get("props"), list) else [],
        }
    return candidate_script_text, out_entities


def _strip_chapter_markers(text: str) -> str:
    # 移除“第1章/第一章”等章节标记（可能被模型重复拷贝进标题/概要）。
    cleaned = str(text or "")
    cleaned = re.sub(r"第\s*(?:\d+|[一二三四五六七八九十百千]+)\s*章[:：]?\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _normalize_script_text(*, script_text: str, max_title_len: int = 18) -> str:
    text = (script_text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    # 1) 标题行：清理重复章节标记、控制长度
    for idx, line in enumerate(lines[:8]):
        if not line.lstrip().startswith("#"):
            continue
        if "《" not in line or "》" not in line:
            continue
        prefix, rest = line.split("《", 1)
        inner, suffix = rest.split("》", 1)
        inner_clean = _strip_chapter_markers(inner)
        if len(inner_clean) > max_title_len:
            inner_clean = inner_clean[:max_title_len].rstrip()
        lines[idx] = f"{prefix}《{inner_clean}》{suffix}"
        break

    # 2) 概要：每条必须单行（合并换行）
    out: List[str] = []
    in_overview = False
    current: str | None = None

    def _flush_current() -> None:
        nonlocal current
        if current is None:
            return
        cleaned = re.sub(r"\s+", " ", current).strip()
        out.append(cleaned)
        current = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## 概要"):
            _flush_current()
            in_overview = True
            out.append(line)
            continue
        if in_overview and stripped.startswith("## "):
            _flush_current()
            in_overview = False
            out.append(line)
            continue
        if not in_overview:
            out.append(line)
            continue

        if line.lstrip().startswith("- 场"):
            _flush_current()
            current = _strip_chapter_markers(line)
            continue

        if current is not None and stripped:
            current = _strip_chapter_markers(f"{current} {line}")
            continue

        _flush_current()
        out.append(line)

    _flush_current()
    return "\n".join(out).strip() + "\n"


def _is_script_text_valid(script_text: str) -> bool:
    text = (script_text or "").strip()
    if not text:
        return False
    required = ("## 概要", "## 分场", "### 场")
    if any(tok not in text for tok in required):
        return False
    # 最少包含一次“节拍/对白/视觉锚点”提示，确保可分镜与一致性信息存在
    if "节拍" not in text or "对白" not in text or "视觉锚点" not in text:
        return False
    return True


def _count_script_scenes(script_text: str) -> int:
    text = script_text or ""
    return len(re.findall(r"(?m)^###\s*场\s*\d+", text))


def _count_source_chars(source_text: str) -> int:
    cleaned = re.sub(r"\s+", "", str(source_text or ""))
    return len(cleaned)


def _auto_max_scenes_from_source(*, source_text: str, quality_mode: str, chars_per_scene: int) -> int:
    """
    动态上限：避免“固定 12 场”在长文本下过度压缩，同时保持安全封顶，防止无限增长。
    """
    char_count = _count_source_chars(source_text)
    cps = max(60, int(chars_per_scene) if chars_per_scene else 120)
    estimated = max(1, (char_count + cps - 1) // cps)

    base_cap = 24 if quality_mode == "quality" else 8
    hard_cap = 60 if quality_mode == "quality" else 24
    return min(hard_cap, max(base_cap, estimated))


def _script_too_short_reason(
    *,
    source_text: str,
    script_text: str,
    min_scenes_hint: int,
) -> str:
    scene_count = _count_script_scenes(script_text)
    if scene_count < int(min_scenes_hint):
        return f"scenes {scene_count} < hint {int(min_scenes_hint)}"

    source_chars = _count_source_chars(source_text)
    script_chars = _count_source_chars(script_text)
    if source_chars >= 800 and script_chars < int(source_chars * 0.6):
        return f"script_chars {script_chars} < 0.6*source_chars {source_chars}"

    return ""


def _estimate_min_scenes_from_source(
    *, source_text: str, min_floor: int, max_scenes: int, chars_per_scene: int
) -> int:
    char_count = _count_source_chars(source_text)
    min_floor_value = max(1, int(min_floor))
    max_scenes_value = max(1, int(max_scenes))
    if min_floor_value > max_scenes_value:
        min_floor_value = max_scenes_value

    cps = int(chars_per_scene) if chars_per_scene else 120
    cps = max(60, cps)
    estimated = max(1, (char_count + cps - 1) // cps)
    return min(max_scenes_value, max(min_floor_value, estimated))


def _count_source_dialogues(source_text: str) -> int:
    """
    统计输入文本中的对白数量（通过引号、冒号等标记识别）。
    用于动态计算剧本中每场的建议对白数量。
    """
    text = str(source_text or "")
    if not text:
        return 0
    
    # 匹配引号内的对话内容（中文引号和英文引号）
    quoted_dialogues = len(re.findall(r'["""「『].*?["""」』]', text))
    
    # 匹配冒号后的对话（如：他说："..."）
    colon_dialogues = len(re.findall(r'[:：]\s*["""「『].*?["""」』]', text))
    
    # 匹配直接对话模式（如：A：... B：...）
    direct_dialogues = len(re.findall(r'[A-Za-z\u4e00-\u9fa5]+[:：][^。！？!?；;\n]{2,}', text))
    
    # 综合估计，避免重复计数
    estimated = max(quoted_dialogues, colon_dialogues, direct_dialogues)
    
    # 如果没有明显标记，按文本长度和标点符号估算
    if estimated == 0:
        # 统计对话式标点（问号、感叹号）的数量
        dialogue_puncts = len(re.findall(r'[？?!！]', text))
        estimated = dialogue_puncts // 2  # 假设每句对话平均有2个标点
    
    return estimated


def _estimate_dialogue_range(
    *, source_text: str, quality_mode: str, estimated_scenes: int
) -> str:
    """
    根据输入文本的实际对白情况动态计算每场的建议对白数量范围。
    
    Args:
        source_text: 输入的章节文本
        quality_mode: 质量模式（standard/quality）
        estimated_scenes: 预估的分场数量
    
    Returns:
        对白数量范围字符串，如 "2~6"
    """
    total_dialogues = _count_source_dialogues(source_text)
    
    if total_dialogues == 0:
        # 没有检测到对白，使用默认范围
        return "6~12" if quality_mode == "quality" else "3~8"
    
    # 根据总对白数量和预估分场数，计算每场的平均对白数
    avg_dialogues_per_scene = max(1, total_dialogues // estimated_scenes) if estimated_scenes > 0 else total_dialogues
    
    # 根据质量模式调整范围
    if quality_mode == "quality":
        # 质量模式：允许更多对白，范围更宽
        min_dialogues = max(2, avg_dialogues_per_scene - 2)
        max_dialogues = min(15, avg_dialogues_per_scene + 6)
    else:
        # 标准模式：范围较窄
        min_dialogues = max(1, avg_dialogues_per_scene - 1)
        max_dialogues = min(10, avg_dialogues_per_scene + 3)
    
    # 确保最小值不大于最大值
    min_dialogues = min(min_dialogues, max_dialogues)
    
    return f"{min_dialogues}~{max_dialogues}"


def _default_min_scene_floor_from_source(source_text: str) -> int:
    cleaned = re.sub(r"\s+", "", str(source_text or ""))
    n = len(cleaned)
    if n < 200:
        return 1
    if n < 600:
        return 4
    return 6


def _extract_character_profiles_from_entities(entities: Dict[str, Any]) -> List[CharacterProfile]:
    """
    从实体抽取结果中提取角色档案
    
    Args:
        entities: 实体抽取结果
    
    Returns:
        角色档案列表
    """
    profiles: List[CharacterProfile] = []
    
    if not isinstance(entities, dict):
        return profiles
    
    characters = entities.get("characters", [])
    if not isinstance(characters, list):
        return profiles
    
    for idx, char in enumerate(characters):
        if not isinstance(char, dict):
            continue
        
        name = char.get("name", "").strip()
        if not name:
            continue
        
        descriptor = char.get("descriptor", "").strip()
        importance = char.get("importance", "secondary").strip()
        
        # 生成唯一ID
        raw_id = char.get("character_id")
        if raw_id is None:
            raw_id = char.get("entity_id") or char.get("id")
        character_id = str(raw_id).strip() if raw_id is not None else ""
        if not character_id:
            character_id = f"char_{idx}_{hash(name) % 10000:04d}"
        
        # 从描述中提取外观和性格特征
        appearance_description = descriptor
        personality_traits = []
        
        # 简单的特征提取（可以根据需要增强）
        if "开朗" in descriptor or "活泼" in descriptor:
            personality_traits.append("开朗")
        if "冷静" in descriptor or "沉稳" in descriptor:
            personality_traits.append("冷静")
        if "温柔" in descriptor or "善良" in descriptor:
            personality_traits.append("温柔")
        if "坚强" in descriptor or "勇敢" in descriptor:
            personality_traits.append("坚强")
        
        profile = CharacterProfile(
            character_id=character_id,
            name=name,
            appearance_description=appearance_description,
            personality_traits=personality_traits,
            importance=importance
        )
        
        profiles.append(profile)
    
    return profiles


def _extract_audio_markers_from_script(script_text: str, entities: Dict[str, Any]) -> List[AudioMarker]:
    """
    从剧本中提取音频标记
    
    Args:
        script_text: 剧本文本
        entities: 实体抽取结果
    
    Returns:
        音频标记列表
    """
    markers: List[AudioMarker] = []
    
    if not isinstance(script_text, str):
        return markers
    
    # 解析剧本中的分场和对白
    lines = script_text.split("\n")
    current_scene = 0
    current_character = ""
    
    for line in lines:
        stripped = line.strip()
        
        # 识别分场
        if re.match(r"^###\s*场\s*(\d+)", stripped):
            match = re.match(r"^###\s*场\s*(\d+)", stripped)
            if match:
                current_scene = int(match.group(1))
        
        # 识别对白
        elif stripped.startswith("- ") and "：" in stripped:
            parts = stripped[2:].split("：", 1)
            if len(parts) == 2:
                character_name = parts[0].strip()
                dialogue_line = parts[1].strip()
                
                if character_name and dialogue_line:
                    marker = AudioMarker(
                        scene_number=current_scene,
                        character_name=character_name,
                        dialogue_line=dialogue_line
                    )
                    markers.append(marker)
    
    return markers


def _generate_character_profiles_with_llm(
    ctx: Any | None = None,
    *,
    source_text: str,
    entities: Dict[str, Any],
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    temperature: float,
) -> List[CharacterProfile]:
    """
    使用LLM生成详细的角色档案
    
    Args:
        source_text: 源文本
        entities: 实体抽取结果
        api_key: API密钥
        base_url: API基础URL
        model: 模型名称
        timeout_s: 超时时间
        temperature: 温度参数
    
    Returns:
        角色档案列表
    """
    system = (
        "你是专业的角色设计师和配音指导。\n"
        "任务：根据【章节文本】和【角色实体】，为每个角色生成详细的角色档案，包括外观描述、性格特征、声音风格等。\n"
        "输出必须是严格 JSON 数组（不要 Markdown 代码块、不要解释文字、不要多余字段）。"
    )
    
    # 准备角色实体信息
    characters_text = ""
    if isinstance(entities, dict) and isinstance(entities.get("characters"), list):
        for char in entities.get("characters", []):
            if isinstance(char, dict):
                name = char.get("name", "").strip()
                descriptor = char.get("descriptor", "").strip()
                importance = char.get("importance", "secondary").strip()
                characters_text += f"- {name}（{importance}）：{descriptor}\n"
    
    user = (
        "请仅输出如下 JSON 数组（只输出 JSON，不要额外文本）：\n"
        "[\n"
        '  {\n'
        '    "character_id": "唯一ID（格式：char_序号_数字）",\n'
        '    "name": "角色名",\n'
        '    "appearance_description": "详细的外观描述（年龄、发型、服装、体型、面部特征等，100-200字）",\n'
        '    "personality_traits": ["性格特征1", "性格特征2", "性格特征3"],\n'
        '    "voice_style": "声音风格（natural/energetic/calm/dramatic等）",\n'
        '    "importance": "重要性（main/important/secondary/crowd）"\n'
        '  }\n'
        "]\n\n"
        "要求：\n"
        "- appearance_description 要详细具体，便于通义万相2.6生成一致的角色形象\n"
        "- personality_traits 要包含3-5个性格特征，用于指导配音和表演\n"
        "- voice_style 要根据角色性格选择合适的风格\n"
        "- importance 要准确反映角色在故事中的重要性\n\n"
        "【章节文本】（用于理解角色背景）：\n"
        f"{(source_text or '')[:8000]}\n\n"
        "【角色实体】（需要生成档案的角色）：\n"
        f"{characters_text}"
    )
    
    try:
        with llm_stream_context(ctx, stage="script", stream_key="character_profiles") as on_chunk:
            content = chat_completions(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                timeout_s=timeout_s,
                temperature=temperature,
                on_chunk=on_chunk,
            )
        
        obj = extract_json_array(content)
        if not isinstance(obj, list):
            return []
        
        profiles: List[CharacterProfile] = []
        for item in obj:
            if not isinstance(item, dict):
                continue
            
            profile = CharacterProfile(
                character_id=item.get("character_id", ""),
                name=item.get("name", ""),
                appearance_description=item.get("appearance_description", ""),
                personality_traits=item.get("personality_traits", []),
                voice_style=item.get("voice_style", "natural"),
                importance=item.get("importance", "secondary")
            )
            
            profiles.append(profile)
        
        return profiles
    except Exception:
        return []


def _generate_audio_markers_with_llm(
    ctx: Any | None = None,
    *,
    script_text: str,
    entities: Dict[str, Any],
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    temperature: float,
) -> List[AudioMarker]:
    """
    使用LLM生成详细的音频标记（遵循阿里云百炼声音公式）
    
    阿里云百炼声音公式：
    提示词 = 主体 + 场景 + 运动 + 声音描述（人声/音效/背景音乐）
    声音描述 = 人声 + 音效 + 背景音乐
    人声 = 角色说话的内容 + 情绪 + 语调 + 语速 + 音色 + 口音
    音效 = 音源材质 + 行为 + 环境音
    背景音乐 = 背景音乐/配乐 + 风格
    
    Args:
        script_text: 剧本文本
        entities: 实体抽取结果
        api_key: API密钥
        base_url: API基础URL
        model: 模型名称
        timeout_s: 超时时间
        temperature: 温度参数
    
    Returns:
        音频标记列表
    """
    system = (
        "你是专业的配音指导和音频设计师，精通阿里云百炼文生视频的声音描述规范。\n"
        "任务：根据【剧本】和【角色实体】，为每句对白生成详细的音频标记。\n"
        "输出必须是严格 JSON 数组（不要 Markdown 代码块、不要解释文字、不要多余字段）。"
    )
    
    user = (
        "请仅输出如下 JSON 数组（只输出 JSON，不要额外文本）：\n"
        "[\n"
        '  {\n'
        '    "scene_number": 场景编号（数字）,\n'
        '    "character_name": "角色名",\n'
        '    "dialogue_line": "对白内容",\n'
        '    "voice_style": "声音风格（natural/energetic/calm/dramatic/whispering等）",\n'
        '    "emotion": "情感（neutral/happy/sad/angry/fearful/surprised/tense/calm/excited等）",\n'
        '    "voice_tone": "语调描述（如：低沉、清亮、沙哑、温柔等）",\n'
        '    "voice_speed": "语速（slow/normal/fast/very_fast）",\n'
        '    "voice_color": "音色描述（如：磁性、甜美、浑厚、清脆等）",\n'
        '    "voice_accent": "口音（如：普通话、粤语、东北话、美式英文等）",\n'
        '    "background_music": "背景音乐描述（格式：场景描述+音乐风格，如：雨夜阴森走廊，悬疑风格背景音乐）",\n'
        '    "sound_effects": ["音效1", "音效2"]\n'
        '  }\n'
        "]\n\n"
        "声音描述规范（遵循阿里云百炼公式）：\n"
        "- emotion 要准确反映对白的情感状态（neutral/happy/sad/angry/fearful/surprised/tense/calm/excited）\n"
        "- voice_tone 要描述语调特征（低沉、清亮、沙哑、温柔、严肃等）\n"
        "- voice_speed 要根据情感和语境选择（slow/normal/fast/very_fast）\n"
        "- voice_color 要描述音色特征（磁性、甜美、浑厚、清脆、温暖等）\n"
        "- voice_accent 要根据角色设定选择（普通话、粤语、东北话、美式英文等）\n"
        "- background_music 要描述场景氛围和音乐风格（如：温馨的客厅，轻快温馨的钢琴配乐）\n"
        "- sound_effects 要描述音源材质+行为+环境音（如：玻璃小球从桌面掉在木质地面上，发出'砰'的声音，室内安静环境）\n\n"
        "示例：\n"
        "{\n"
        '  "scene_number": 1,\n'
        '  "character_name": "小明",\n'
        '  "dialogue_line": "我要去上学了",\n'
        '  "voice_style": "energetic",\n'
        '  "emotion": "happy",\n'
        '  "voice_tone": "清亮",\n'
        '  "voice_speed": "fast",\n'
        '  "voice_color": "甜美",\n'
        '  "voice_accent": "普通话",\n'
        '  "background_music": "清晨阳光明媚的街道，轻快活泼的童谣风格配乐",\n'
        '  "sound_effects": ["书包拉链拉开的声音", "脚步声"]\n'
        "}\n\n"
        "【剧本】：\n"
        f"{(script_text or '')[:10000]}\n\n"
        "【角色实体】：\n"
        f"{str(entities)[:4000]}"
    )
    
    try:
        with llm_stream_context(ctx, stage="script", stream_key="audio_markers") as on_chunk:
            content = chat_completions(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                timeout_s=timeout_s,
                temperature=temperature,
                on_chunk=on_chunk,
            )
        
        obj = extract_json_array(content)
        if not isinstance(obj, list):
            return []
        
        markers: List[AudioMarker] = []
        for item in obj:
            if not isinstance(item, dict):
                continue
            
            marker = AudioMarker(
                scene_number=item.get("scene_number", 0),
                character_name=item.get("character_name", ""),
                dialogue_line=item.get("dialogue_line", ""),
                voice_style=item.get("voice_style", "natural"),
                emotion=item.get("emotion", "neutral"),
                background_music=item.get("background_music", ""),
                sound_effects=item.get("sound_effects", []),
                voice_tone=item.get("voice_tone", ""),
                voice_speed=item.get("voice_speed", ""),
                voice_color=item.get("voice_color", ""),
                voice_accent=item.get("voice_accent", "")
            )
            
            markers.append(marker)
        
        return markers
    except Exception:
        return []


def _split_text_into_scene_parts(text: str, *, desired_parts: int, max_parts: int) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []

    desired = max(1, int(desired_parts))
    max_p = max(1, int(max_parts))
    desired = min(desired, max_p)

    parts = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    if not parts:
        parts = [raw]

    def _split_once(idx: int) -> bool:
        if idx < 0 or idx >= len(parts):
            return False
        block = parts[idx].strip()
        if not block:
            return False

        # 优先按句子边界拆分（尽量不破坏语义）
        sentences = [s.strip() for s in re.split(r"[。！？!?；;]+", block) if s.strip()]
        if len(sentences) >= 2:
            mid = max(1, len(sentences) // 2)
            left = "。".join(sentences[:mid]).strip()
            right = "。".join(sentences[mid:]).strip()
        else:
            # 兜底：按长度拆分
            mid = max(1, len(block) // 2)
            left = block[:mid].strip()
            right = block[mid:].strip()

        if not left or not right:
            return False

        parts[idx : idx + 1] = [left, right]
        return True

    # 不足时不断拆最长段，直到达到 desired
    guard = 0
    while len(parts) < desired and guard < 10_000:
        guard += 1
        idx = max(range(len(parts)), key=lambda i: len(parts[i]))
        if not _split_once(idx):
            break

    if len(parts) > max_p:
        parts = parts[:max_p]
    if len(parts) > desired:
        parts = parts[:desired]
    return parts


def run(ctx: Any) -> None:
    """
    生成"剧本草稿"（script_text）与可选的实体抽取（script_entities）。
    - 强制使用 LLM 生成，失败则抛出异常。
    - 默认要求人工审核（script_requires_review=True），审核通过后才进入分镜阶段。
    """
    payload = ctx.payload if isinstance(getattr(ctx, "payload", None), dict) else {}

    existing_script = payload.get("script_text")
    existing_review = payload.get("script_review") if isinstance(payload.get("script_review"), dict) else None
    if isinstance(existing_script, str) and existing_script.strip() and bool((existing_review or {}).get("approved")):
        payload["script_requires_review"] = False
        ctx.payload = payload
        return

    source_text = str(payload.get("source_text") or "")
    require_review = env_flag("DREAMWEAVER_REQUIRE_SCRIPT_APPROVAL", default=True)
    enable_llm = env_flag("DREAMWEAVER_SCRIPT_ENABLE_LLM", default=True)
    require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag(
        "DREAMWEAVER_SCRIPT_REQUIRE_LLM", default=False
    )
    quality_mode = str(payload.get("quality_mode") or "").strip().lower()
    default_max_scenes = 0 if quality_mode == "quality" else 8
    max_scenes_raw = _env_int("DREAMWEAVER_SCRIPT_MAX_SCENES", default_max_scenes)
    min_scenes_floor_default = _default_min_scene_floor_from_source(source_text)
    min_scenes_floor = max(1, _env_int("DREAMWEAVER_SCRIPT_MIN_SCENES", min_scenes_floor_default))
    chars_per_scene = max(60, _env_int("DREAMWEAVER_SCRIPT_CHARS_PER_SCENE", 120))
    hint_chars_per_scene = max(60, _env_int("DREAMWEAVER_SCRIPT_HINT_CHARS_PER_SCENE", max(300, chars_per_scene)))
    if max_scenes_raw <= 0:
        max_scenes = _auto_max_scenes_from_source(source_text=source_text, quality_mode=quality_mode, chars_per_scene=chars_per_scene)
        max_scenes_mode = "auto"
    else:
        max_scenes = max(1, int(max_scenes_raw))
        max_scenes_mode = "fixed"

    min_scenes_hint = _estimate_min_scenes_from_source(
        source_text=source_text,
        min_floor=min_scenes_floor,
        max_scenes=max_scenes,
        chars_per_scene=hint_chars_per_scene,
    )

    ensure_style_payload(payload)
    style_prompt = str(payload.get("style_prompt") or "")

    model = _pick_dreamweaver_script_model()
    llm_runtime = resolve_llm_runtime_config(model)
    api_key = llm_runtime.api_key
    base_url = llm_runtime.base_url
    timeout_s = int(os.getenv("DREAMWEAVER_SCRIPT_TIMEOUT", "180") or "180")
    temperature = _env_float("DREAMWEAVER_SCRIPT_TEMPERATURE", 0.3)
    if temperature < 0.0:
        temperature = 0.0
    if temperature > 1.0:
        temperature = 1.0

    can_llm = bool(enable_llm and api_key and base_url)
    if require_llm and not can_llm:
        raise RuntimeError(
            f"{llm_runtime.api_key_env} and {llm_runtime.base_url_env} are required for script generation"
        )

    if not can_llm:
        fallback_text = (source_text or "").strip()
        if not fallback_text:
            fallback_text = (
                "# 剧本（草稿）\n\n"
                "## 概要\n"
                "- （空）\n\n"
                "## 分场\n"
                "### 场1 | 内景 | 未知 | 日\n"
                "人物：\n"
                "- （待补全）\n"
                "节拍：\n"
                "- （待补全）\n"
                "对白：\n"
                "- （待补全）\n"
                "视觉锚点：\n"
                "- （待补全）\n"
            )

        payload["script_text"] = fallback_text
        payload["script_entities"] = {"characters": [], "scenes": [], "props": []}
        payload["script_generation"] = {
            "mode": "rule",
            "reason": "llm_disabled_or_missing_env",
            "max_scenes": int(max_scenes),
            "max_scenes_mode": max_scenes_mode,
            "min_scenes_hint": int(min_scenes_hint),
        }
        payload["script_review"] = {"approved": not bool(require_review), "mode": "auto"}
        payload["script_requires_review"] = bool(require_review)
        ctx.payload = payload
        return

    mode = "llm"
    script_text = ""
    entities: Dict[str, Any] = {"characters": [], "scenes": [], "props": []}
    llm_warnings: List[str] = []

    try:
            retries_default = 2 if quality_mode == "quality" else 1
            max_retries = max(0, _env_int("DREAMWEAVER_SCRIPT_LLM_RETRIES", retries_default))
            dialogue_range = _estimate_dialogue_range(
                source_text=source_text,
                quality_mode=quality_mode,
                estimated_scenes=min_scenes_hint,
            )
            beats_range = "3~6" if quality_mode == "quality" else "2~4"
            hint_max_scenes = min(max_scenes, min_scenes_hint + 4)

            system = (
                "你是专业短剧编剧、导演助理与制片协同。\n"
                "任务：把【章节文本】改写为可直接用于分镜/首尾帧/视频生成的【短剧剧本草稿】，并抽取可复用素材库实体。\n"
                "输出必须是严格 JSON 对象（不要 Markdown 代码块、不要解释文字、不要多余字段）。"
            )

            user_first = (
                "请输出如下 JSON（只输出 JSON，不要额外文本）：\n"
                "{\n"
                '  "script_text": "Markdown 剧本草稿（必须包含标题/概要/分场；每场包含时段/内外/地点、人物、节拍、对白短句对打、视觉锚点；避免长段旁白）",\n'
                '  "entities": {\n'
                '    "characters": [{"name": "角色名", "descriptor": "外观+气质+关键特征", "importance": "主角|重要|次要|群像"}],\n'
                '    "scenes": [{"name": "场景名", "descriptor": "空间/氛围/时间/天气/风格"}],\n'
                '    "props": [{"name": "道具名", "descriptor": "材质/外观/用途/关键特征"}]\n'
                "  }\n"
                "}\n\n"
                "指导原则（由你自主判断，不要机械凑数）：\n"
                f"- 分场数量由你根据剧情节拍决定；参考：本章建议约 {min_scenes_hint}~{hint_max_scenes} 场；系统安全上限 {max_scenes} 场（超出会被判无效）\n"
                "- 概要：每条一行，格式为“- 场X：一句话摘要（<=40字）”，不得换行，不要包含“第X章/第一章”等章节标记\n"
                f"- 每场对白 {dialogue_range} 句，尽量短句对打（避免连续长独白/术语堆砌）\n"
                f"- 每场节拍 {beats_range} 条（动作/反应/推进），用于分镜拆解\n"
                "- 不要出现需要画面生成的清晰文字/数字/图表内容（可写“手绘曲线/不可读标注”）\n"
                "- 不要出现水印、字幕、UI 文案等要求\n\n"
                f"视觉风格（仅用于“视觉锚点/氛围”字段，不要改写剧情设定）：{style_prompt}\n\n"
                "推荐 Markdown 模板（务必贴合）：\n"
                "# 剧本（草稿）：《标题》\n"
                "## 概要\n"
                "- 场1：...\n"
                "## 分场\n"
                "### 场1 | 内景/外景 | 地点 | 时段\n"
                "人物：A/B/群像\n"
                "节拍：\n"
                "- ...\n"
                "对白：\n"
                "- A：...\n"
                "- B：...\n"
                "视觉锚点：\n"
                "- 角色外观：...\n"
                "- 场景元素：...\n"
                "- 道具：...\n\n"
                "章节文本：\n"
                f"{source_text[:12000]}"
            )

            user = user_first
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    with llm_stream_context(ctx, stage="script", stream_key="script") as on_chunk:
                        content = chat_completions(
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                            timeout_s=timeout_s,
                            temperature=temperature,
                            on_chunk=on_chunk,
                        )
                    obj = extract_json_object(content)
                    if not isinstance(obj, dict) or not isinstance(obj.get("script_text"), str):
                        raise RuntimeError("invalid LLM output: missing script_text JSON field")

                    candidate_script = _normalize_script_text(script_text=obj["script_text"])
                    if not _is_script_text_valid(candidate_script):
                        raise RuntimeError("invalid script_text: missing required sections/template markers")

                    scene_count = _count_script_scenes(candidate_script)
                    if scene_count > max_scenes:
                        raise RuntimeError(f"invalid script_text: scenes {scene_count} > cap {max_scenes}")

                    too_short_reason = _script_too_short_reason(
                        source_text=source_text,
                        script_text=candidate_script,
                        min_scenes_hint=min_scenes_hint,
                    )
                    if too_short_reason and attempt < max_retries:
                        user = (
                            "请基于【上一次输出的剧本】进行扩写与拆分（只输出 JSON，不要额外文本）：\n"
                            "{\n"
                            '  "script_text": "Markdown 剧本草稿（必须包含标题/概要/分场；每场包含时段/内外/地点、人物、节拍、对白短句对打、视觉锚点）",\n'
                            '  "entities": {\n'
                            '    "characters": [{"name": "角色名", "descriptor": "外观+气质+关键特征", "importance": "主角|重要|次要|群像"}],\n'
                            '    "scenes": [{"name": "场景名", "descriptor": "空间/氛围/时间/天气/风格"}],\n'
                            '    "props": [{"name": "道具名", "descriptor": "材质/外观/用途/关键特征"}]\n'
                            "  }\n"
                            "}\n\n"
                            f"原因：当前输出偏短（{too_short_reason}），会导致后续分镜/视频时长过短。\n"
                            "扩写要求：\n"
                            f"- 分场数量由你根据节拍决定，但请明显增加拆分密度；参考不少于 {min_scenes_hint} 场，并保持不超过 {max_scenes} 场\n"
                            f"- 每场对白 {dialogue_range} 句、每场节拍 {beats_range} 条；不要用“……/略/待补全”占位\n"
                            "- 保持剧情不串台、不新增离题支线；补足动作反应与情绪推进，让节拍更细\n"
                            "- 仍需遵守：不要出现清晰文字/数字/图表、水印/字幕/UI 文案\n\n"
                            "【上一次输出的剧本】（需要扩写）：\n"
                            f"{candidate_script[:12000]}\n\n"
                            "【章节文本】（供核对）：\n"
                            f"{source_text[:12000]}"
                        )
                        continue

                    script_text = candidate_script
                    ent = obj.get("entities")
                    if isinstance(ent, dict):
                        entities = {
                            "characters": ent.get("characters") if isinstance(ent.get("characters"), list) else [],
                            "scenes": ent.get("scenes") if isinstance(ent.get("scenes"), list) else [],
                            "props": ent.get("props") if isinstance(ent.get("props"), list) else [],
                        }
                    mode = "llm"
                    if too_short_reason:
                        llm_warnings.append(f"script may be too short: {too_short_reason}")
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt >= max_retries:
                        raise
                    user = (
                        "请重新输出严格 JSON（只输出 JSON，不要额外文本；不要 Markdown 代码块；不要解释）。\n"
                        "要求：必须包含标题/概要/分场结构，并严格使用模板中的关键字段（人物/节拍/对白/视觉锚点）。\n"
                        f"系统安全上限：分场不要超过 {max_scenes} 场。\n\n"
                        "章节文本：\n"
                        f"{source_text[:12000]}"
                    )
            if mode != "llm" or not script_text.strip():
                raise RuntimeError(f"invalid LLM output: missing script_text ({last_exc})")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"script LLM failed: {exc}") from exc

    # 二次润色：优先用于提升可拍性与一致性（默认仅 quality_mode 开启，且失败自动回退原稿）
    enhance_enabled = _should_enable_script_enhance(payload=payload)
    if enhance_enabled:
        try:
            enhance_model = _pick_dreamweaver_script_enhance_model()
            enhance_timeout_s = int(os.getenv("DREAMWEAVER_SCRIPT_ENHANCE_TIMEOUT", "180") or "180")
            enhance_temperature = _env_float("DREAMWEAVER_SCRIPT_ENHANCE_TEMPERATURE", 0.2)
            if enhance_temperature < 0.0:
                enhance_temperature = 0.0
            if enhance_temperature > 1.0:
                enhance_temperature = 1.0

            enhanced_text, enhanced_entities = _llm_enhance_script(
                source_text=source_text,
                script_text=script_text,
                entities=entities,
                style_prompt=style_prompt,
                api_key=api_key,
                base_url=base_url,
                model=enhance_model,
                timeout_s=enhance_timeout_s,
                temperature=enhance_temperature,
                max_scenes=max_scenes,
                estimated_scenes=min_scenes_hint,
                quality_mode=quality_mode,
            )
            script_text = enhanced_text
            entities = enhanced_entities
            payload["script_enhancement"] = {"mode": "llm", "model": enhance_model}
        except Exception as exc:  # noqa: BLE001
            llm_warnings.append(f"script enhance skipped: {_format_llm_error(exc)}")
            payload["script_enhancement"] = {"mode": "failed", "error": _format_llm_error(exc)}
    else:
        payload["script_enhancement"] = {"mode": "disabled"}

    payload["script_text"] = script_text
    payload["script_entities"] = entities
    payload["script_generation"] = {
        "mode": mode,
        "model": model if mode.startswith("llm") else None,
        "warnings": llm_warnings,
        "max_scenes": max_scenes,
        "max_scenes_mode": max_scenes_mode,
        "min_scenes_hint": min_scenes_hint,
        "chars_per_scene": chars_per_scene,
        "hint_chars_per_scene": hint_chars_per_scene,
    }
    payload["script_review"] = {"approved": False}
    payload["script_requires_review"] = bool(require_review)
    
    # 生成角色档案和音频标记（支持通义万相2.6）
    enable_character_profiles = env_flag("DREAMWEAVER_ENABLE_CHARACTER_PROFILES", default=True)
    enable_audio_markers = env_flag("DREAMWEAVER_ENABLE_AUDIO_MARKERS", default=True)
    
    character_profiles: List[CharacterProfile] = []
    audio_markers: List[AudioMarker] = []
    
    if enable_character_profiles and can_llm:
        try:
            character_profiles = _generate_character_profiles_with_llm(
                ctx,
                source_text=source_text,
                entities=entities,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_s=timeout_s,
                temperature=temperature,
            )
            
            if not character_profiles:
                llm_warnings.append("character profiles generation failed, using fallback")
                character_profiles = _extract_character_profiles_from_entities(entities)
            
            payload["character_profiles"] = [p.to_dict() for p in character_profiles]
        except Exception as exc:
            llm_warnings.append(f"character profiles generation error: {_format_llm_error(exc)}")
            character_profiles = _extract_character_profiles_from_entities(entities)
            payload["character_profiles"] = [p.to_dict() for p in character_profiles]
    elif enable_character_profiles:
        character_profiles = _extract_character_profiles_from_entities(entities)
        payload["character_profiles"] = [p.to_dict() for p in character_profiles]
    
    if enable_audio_markers and can_llm:
        try:
            audio_markers = _generate_audio_markers_with_llm(
                ctx,
                script_text=script_text,
                entities=entities,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_s=timeout_s,
                temperature=temperature,
            )
            
            if not audio_markers:
                llm_warnings.append("audio markers generation failed, using fallback")
                audio_markers = _extract_audio_markers_from_script(script_text, entities)
            
            payload["audio_markers"] = [m.to_dict() for m in audio_markers]
        except Exception as exc:
            llm_warnings.append(f"audio markers generation error: {_format_llm_error(exc)}")
            audio_markers = _extract_audio_markers_from_script(script_text, entities)
            payload["audio_markers"] = [m.to_dict() for m in audio_markers]
    elif enable_audio_markers:
        audio_markers = _extract_audio_markers_from_script(script_text, entities)
        payload["audio_markers"] = [m.to_dict() for m in audio_markers]

    ctx.payload = payload
