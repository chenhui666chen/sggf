"""
SoundEffectDesigner - 音效设计师Agent

核心职责：
1. 设计场景音效和环境音
2. 规划音效的触发时机和时长
3. 确保音效层次合理（避免过载）
"""

import logging
import json
import os
import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

import httpx
import requests
from app.core.config import settings
from core.model_resolution import TaskType
from app.services.audiobook.llm_client import (
    call_audiobook_llm_async,
    call_audiobook_llm_sync,
)
from app.services.audiobook.llm_config import get_audiobook_llm_model
from app.services.audiobook.llm_json import parse_llm_json_object
from app.services.audiobook.ai_music import AIMusicGenerator, MusicGenerationResult, create_music_generator
from app.services.audiobook.audio_asset_cloud_storage import upload_audio_library_asset
from app.services.audiobook.audio_library_asset_repository import upsert_audio_library_asset
from app.services.audiobook.vidu_timing2audio_generator import ViduTiming2AudioGenerator, create_vidu_timing2audio_generator
from app.services.audiobook.duration_estimator import estimate_narration_duration_seconds
from app.db.base import SessionLocal

logger = logging.getLogger(__name__)

# 音效资源与索引默认路径（相对 backend/ 计算）
BACKEND_DIR = Path(__file__).resolve().parents[4]
AUDIO_LIBRARY_DIR = BACKEND_DIR / "data" / "audio_library"
SOUND_EFFECTS_DIR = AUDIO_LIBRARY_DIR / "sound_effects"
DEFAULT_INDEX_PATH = AUDIO_LIBRARY_DIR / "sound_effects_index.json"
VALID_EFFECT_CATEGORIES = {"environment", "action", "emotion", "transition"}
EFFECT_PROMPT_ENRICHMENTS = (
    (
        ("灵石", "晶石", "宝石", "玉石"),
        "清脆的晶石/玉石轻微碰撞声，带一点奇幻灵力闪烁感，短促干净",
    ),
    (
        ("纸张", "书页", "纸页", "医案"),
        "干燥纸页被手指翻动或摩擦的簌簌声，近景，细碎自然",
    ),
    (
        ("火把", "火折", "点燃", "引火"),
        "火把被点燃的短促噗燃声，随后有轻微火焰噼啪声",
    ),
    (
        ("呼喊", "喊声", "叫喊", "回声"),
        "远处人声呼喊的空间回声，模糊、带距离感，不要清晰台词",
    ),
    (
        ("骨裂", "骨骼", "脆响", "龟裂"),
        "低沉短促的骨裂脆响，带轻微身体冲击感，克制不血腥",
    ),
    (
        ("倒地", "摔倒", "轰然倒地"),
        "人体或重物倒地的沉闷撞击声，短促有重量",
    ),
)

class EffectType(str, Enum):
    """音效类型"""
    ENVIRONMENT = "environment"  # 环境音（持续）
    ACTION = "action"  # 动作音（点缀）
    EMOTION = "emotion"  # 情绪音（氛围）
    TRANSITION = "transition"  # 转场音


@dataclass
class SoundEffectCue:
    """音效提示"""
    scene_id: str
    timestamp: float  # 触发时间（秒）
    effect_type: EffectType
    description: str  # 音效描述，如"雨声渐密"
    audio_file: str = ""  # 音效文件路径
    volume: float = 0.3  # 音量（0-1）
    fade_in: float = 0.0  # 淡入时长（秒）
    fade_out: float = 0.0  # 淡出时长（秒）
    loop: bool = False  # 是否循环
    duration: float = 0.0  # 持续时长（秒，0表示直到结束）
    mix_mode: str = "background"  # background/foreground
    effect_id: str = ""



class SoundEffectDesigner:
    """
    音效设计师Agent
    
    基于剧本标注设计场景音效
    """
    
    def __init__(
        self,
        index_path: Optional[str] = None,
        llm_client=None,
    ):
        """音效设计师

        Args:
            index_path: 外部音效索引文件路径（可选），默认使用 DEFAULT_INDEX_PATH
            llm_client: LLM客户端（可选，用于智能音效匹配）
        """
        self.llm_client = llm_client
        self._music_generator: Optional[AIMusicGenerator] = None
        self._vidu_generator: Optional[ViduTiming2AudioGenerator] = None

        # 内置占位音效库
        self.sound_library = self._init_sound_library()
        # 尝试从外部索引加载扩展音效库
        self.index_path = Path(index_path) if index_path else DEFAULT_INDEX_PATH
        self.audio_library_dir = self.index_path.parent
        self.sound_effects_dir = self.audio_library_dir / "sound_effects"
        self._load_external_sound_library()

        self.effect_cues: List[SoundEffectCue] = []
        
    
    def _init_sound_library(self) -> Dict[str, Dict[str, Any]]:
        """初始化音效库（占位）"""
        return {
            # 环境音
            "rain_light": {"type": "environment", "file": "rain_light.mp3", "description": "小雨"},
            "rain_heavy": {"type": "environment", "file": "rain_heavy.mp3", "description": "大雨"},
            "wind": {"type": "environment", "file": "wind.mp3", "description": "风声"},
            "city_ambient": {"type": "environment", "file": "city.mp3", "description": "城市环境音"},
            "forest_ambient": {"type": "environment", "file": "forest.mp3", "description": "森林环境音"},
            
            # 动作音
            "footsteps": {"type": "action", "file": "footsteps.mp3", "description": "脚步声"},
            "door_open": {"type": "action", "file": "door_open.mp3", "description": "开门声"},
            "door_close": {"type": "action", "file": "door_close.mp3", "description": "关门声"},
            "paper_rustle": {
                "type": "action",
                "file": "paper.mp3",
                "description": "纸张簌簌声",
                "tags": ["纸张", "纸页", "书页", "摩擦", "翻动", "医案"],
            },
            "torch_ignite": {
                "type": "action",
                "file": "torch_ignite.mp3",
                "description": "火把点燃声",
                "tags": ["火把", "点燃", "火折", "火焰", "噗燃"],
            },
            "crystal_clink": {
                "type": "action",
                "file": "crystal_clink.mp3",
                "description": "晶石碰撞声",
                "tags": ["灵石", "晶石", "宝石", "玉石", "碰撞", "清脆"],
            },
            "keyboard": {"type": "action", "file": "keyboard.mp3", "description": "键盘声"},
            
            # 情绪音
            "heartbeat": {"type": "emotion", "file": "heartbeat.mp3", "description": "心跳声"},
            "breath_heavy": {"type": "emotion", "file": "breath.mp3", "description": "沉重呼吸"},
            "gasp": {"type": "emotion", "file": "gasp.mp3", "description": "倒吸气"},
            "distant_shout_echo": {
                "type": "emotion",
                "file": "distant_shout_echo.mp3",
                "description": "远处呼喊回声",
                "tags": ["远处", "呼喊", "喊声", "回声", "距离感"],
            },
        }
    
    def design_effects(
        self,
        script_segments: List[Dict[str, Any]],
        scene_info: Optional[Dict[str, Any]] = None,
        allow_asset_generation: bool = True,
    ) -> List[SoundEffectCue]:
        """
        设计音效方案
        
        Args:
            script_segments: 剧本片段列表
                [
                    {
                        "text": "林墨走在雨中的街道上",
                        "sound_effects": ["rain_heavy", "footsteps"],
                        "timestamp": 0.0
                    }
                ]
            scene_info: 场景信息（可选）
            allow_asset_generation: 是否允许生成新素材
        
        Returns:
            音效提示列表
        """
        logger.info(f"🎵 设计音效方案: {len(script_segments)} 个片段...")
        
        effect_cues = []
        current_time = 0.0
        
        for i, segment in enumerate(script_segments):
            segment_effects = segment.get("sound_effects", [])
            
            for effect_desc in segment_effects:
                effect_request = self._normalize_effect_request(effect_desc)
                description = effect_request.get("description", "")
                if not description:
                    continue
                # 匹配音效库
                effect_cue = self._match_effect(
                    description=description,
                    timestamp=current_time,
                    scene_id=f"scene_{i}",
                    effect_request=effect_request,
                )
                
                if effect_cue:
                    effect_cues.append(effect_cue)
            
            current_time += estimate_narration_duration_seconds(segment.get("text", ""))
        
        self.effect_cues = effect_cues

        # 优化音效密度，避免过载
        optimized = self.optimize_effect_density()
        logger.info(f"   ✅ 设计完成: {len(effect_cues)} → {len(optimized)} 个音效提示（含密度优化）")
        
        return optimized
    
    def _match_effect(
        self,
        description: str,
        timestamp: float,
        scene_id: str,
        effect_request: Optional[Dict[str, Any]] = None,
    ) -> Optional[SoundEffectCue]:
        """匹配音效库

        匹配优先级：
        1. 直接按ID精确匹配（description 作为音效ID）
        2. 按描述与音效 description 的包含关系匹配
        3. 按 tags 关键词匹配
        4. 若仍未命中，返回占位音效
        """
        # 1. 精确ID匹配（如剧本直接给出 "rain_heavy"）
        if description in self.sound_library:
            effect_info = self.sound_library[description]
            effect_type = self._coerce_effect_type(effect_info.get("type"))
            file_path = effect_info["file"]
            return self._apply_effect_request_overrides(SoundEffectCue(
                scene_id=scene_id,
                timestamp=timestamp,
                effect_type=effect_type,
                description=description,
                audio_file=file_path,
                volume=0.3 if effect_type == EffectType.ENVIRONMENT else 0.5,
                fade_in=2.0 if effect_type == EffectType.ENVIRONMENT else 0.5,
                fade_out=2.0 if effect_type == EffectType.ENVIRONMENT else 0.5,
                loop=(effect_type == EffectType.ENVIRONMENT),
                duration=10.0 if effect_type == EffectType.ENVIRONMENT else 2.0,
                mix_mode="background" if effect_type == EffectType.ENVIRONMENT else "foreground",
                effect_id=description,
            ), effect_request)

        # 2. 描述+标签匹配
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0
        best_is_resolvable = False

        for effect_name, effect_info in self.sound_library.items():
            desc_text = effect_info.get("description", "")
            tags = effect_info.get("tags", [])

            score = 0
            # 描述包含匹配
            if desc_text and (desc_text in description or description in desc_text):
                score += 2

            # 标签匹配：如果有任何 tag 出现在 description 中，加分
            for tag in tags:
                if tag and tag in description:
                    score += 1

            is_resolvable = self._has_resolvable_audio_file(effect_info.get("file", ""))
            if score > best_score or (score == best_score and score > 0 and is_resolvable and not best_is_resolvable):
                best_score = score
                best_match = {"name": effect_name, "info": effect_info}
                best_is_resolvable = is_resolvable

        if best_match and best_score > 0:
            effect_info = best_match["info"]
            effect_type = self._coerce_effect_type(effect_info.get("type"))
            file_path = effect_info["file"]
            return self._apply_effect_request_overrides(SoundEffectCue(
                scene_id=scene_id,
                timestamp=timestamp,
                effect_type=effect_type,
                description=description,
                audio_file=file_path,
                volume=0.3 if effect_type == EffectType.ENVIRONMENT else 0.5,
                fade_in=2.0 if effect_type == EffectType.ENVIRONMENT else 0.5,
                fade_out=2.0 if effect_type == EffectType.ENVIRONMENT else 0.5,
                loop=(effect_type == EffectType.ENVIRONMENT),
                duration=10.0 if effect_type == EffectType.ENVIRONMENT else 2.0,
                mix_mode="background" if effect_type == EffectType.ENVIRONMENT else "foreground",
                effect_id=str(best_match["name"]),
            ), effect_request)

        # 3. 未找到匹配，创建占位
        logger.warning(f"⚠️ 未找到音效: {description}，使用占位")
        inferred_type = self._infer_effect_type_from_description(description)
        default_duration = 8.0 if inferred_type == EffectType.ENVIRONMENT else 3.0
        return self._apply_effect_request_overrides(SoundEffectCue(
            scene_id=scene_id,
            timestamp=timestamp,
            effect_type=inferred_type,
            description=description,
            audio_file="placeholder.mp3",
            volume=0.18 if inferred_type == EffectType.ENVIRONMENT else 0.3,
            fade_in=2.0 if inferred_type == EffectType.ENVIRONMENT else 0.0,
            fade_out=2.0 if inferred_type == EffectType.ENVIRONMENT else 0.5,
            loop=inferred_type == EffectType.ENVIRONMENT,
            duration=default_duration,
            mix_mode="background" if inferred_type == EffectType.ENVIRONMENT else "foreground",
        ), effect_request)

    def _normalize_effect_request(self, value: Any) -> Dict[str, Any]:
        """将字符串/字典/音效对象统一成内部音效请求。"""
        if isinstance(value, str):
            return {"description": value.strip()}
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = dict(getattr(value, "__dict__", {}) or {})

        description = (
            data.get("name")
            or data.get("effect")
            or data.get("id")
            or data.get("description")
            or data.get("prompt")
            or ""
        )
        request = dict(data)
        request["description"] = str(description or "").strip()
        return request

    def _apply_effect_request_overrides(
        self,
        cue: SoundEffectCue,
        effect_request: Optional[Dict[str, Any]] = None,
    ) -> SoundEffectCue:
        """保留剧本中已经给出的音效层级、音量、时长、淡入淡出和延迟。"""
        if not effect_request:
            return cue

        requested_type = (
            effect_request.get("effect_type")
            or effect_request.get("type")
            or effect_request.get("layer")
            or ""
        )
        if requested_type:
            cue.effect_type = self._coerce_effect_type(requested_type, default=cue.effect_type)
            cue.loop = cue.loop or cue.effect_type == EffectType.ENVIRONMENT
            cue.mix_mode = "background" if cue.effect_type == EffectType.ENVIRONMENT else cue.mix_mode

        timing = str(effect_request.get("timing") or "").strip().lower()
        if timing == "continuous":
            cue.loop = True
            cue.effect_type = EffectType.ENVIRONMENT
            cue.mix_mode = "background"

        if effect_request.get("volume") is not None:
            cue.volume = self._coerce_float(effect_request.get("volume"), cue.volume, 0.0, 1.0)
        if effect_request.get("duration") is not None:
            cue.duration = self._coerce_float(effect_request.get("duration"), cue.duration, 0.0, 120.0)
        if effect_request.get("fade_in") is not None:
            cue.fade_in = self._coerce_float(effect_request.get("fade_in"), cue.fade_in, 0.0, 30.0)
        if effect_request.get("fade_out") is not None:
            cue.fade_out = self._coerce_float(effect_request.get("fade_out"), cue.fade_out, 0.0, 30.0)
        if effect_request.get("delay") is not None:
            cue.timestamp += self._coerce_float(effect_request.get("delay"), 0.0, 0.0, 60.0)
        if effect_request.get("mix_mode"):
            cue.mix_mode = str(effect_request.get("mix_mode") or cue.mix_mode).strip() or cue.mix_mode

        return cue

    def _coerce_float(self, value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = float(default)
        return max(minimum, min(maximum, parsed))

    def _coerce_effect_type(self, value: Any, default: EffectType = EffectType.ACTION) -> EffectType:
        normalized = self._normalize_effect_category(value, default=default.value)
        try:
            return EffectType(normalized)
        except ValueError:
            return default

    def _normalize_effect_category(self, value: Any, default: str = "action") -> str:
        raw = str(value or "").strip().lower().replace("\\", "/")
        if not raw:
            return default
        alias_map = {
            "bottom": "environment",
            "ambient": "environment",
            "atmosphere": "emotion",
            "sfx": "action",
            "effects": "action",
        }
        raw = alias_map.get(raw, raw)
        if raw in VALID_EFFECT_CATEGORIES:
            return raw
        parts = [alias_map.get(part, part) for part in raw.split("/") if part]
        for part in parts:
            if part in VALID_EFFECT_CATEGORIES:
                return part
        return default

    def _normalize_effect_style(self, value: Any, default: str = "realistic") -> str:
        valid_styles = {"cinematic", "realistic", "fantasy", "scifi", "horror", "peaceful", "intense"}
        raw = str(value or "").strip().lower().replace("\\", "/")
        if not raw:
            return default
        if raw in valid_styles:
            return raw
        if "/" in raw:
            candidate = raw.split("/", 1)[1].strip()
            if candidate in valid_styles:
                return candidate
        return default

    def _infer_effect_style_from_description(self, description: str, effect_type: EffectType, mood: str = "") -> str:
        text = f"{description} {mood}".strip().lower()
        if effect_type == EffectType.TRANSITION:
            return "cinematic"
        if any(key in text for key in ("魔法", "奇幻", "幻想", "法阵", "咒", "灵石", "晶石", "宝石", "法术", "fantasy")):
            return "fantasy"
        if any(key in text for key in ("恐怖", "惊悚", "诡异", "阴森", "幽灵", "鬼", "怪物", "噩梦", "horror", "creepy", "eerie")):
            return "horror"
        if any(key in text for key in ("战斗", "打斗", "追逐", "爆炸", "冲击", "紧张", "爆发", "枪", "剑", "撞击", "奔跑", "battle", "combat", "fight", "intense")):
            return "intense"
        if effect_type == EffectType.ACTION:
            return "realistic"
        if any(key in text for key in ("平静", "宁静", "轻柔", "舒缓", "安静", "温柔", "peace", "calm", "soft", "gentle", "romantic")):
            return "peaceful"
        if mood in {"tense", "epic"}:
            return "intense" if mood == "tense" else "cinematic"
        if mood in {"sad", "calm", "peaceful"}:
            return "peaceful"
        return "realistic"

    def _infer_usage_scenes_from_description(self, description: str, effect_type: EffectType) -> List[str]:
        text = str(description or "").lower()
        scenes: List[str] = []

        def add(scene: str) -> None:
            if scene not in scenes:
                scenes.append(scene)

        indoor_keywords = (
            "室内", "屋内", "房间", "屋里", "门", "走廊", "大厅", "客厅", "卧室", "厨房",
            "书房", "办公室", "教室", "药铺", "殿", "宫", "旅店", "地下室", "地窖",
            "indoor", "room", "inside", "interior",
        )
        outdoor_keywords = (
            "室外", "屋外", "街", "街道", "路上", "路边", "森林", "山", "野外", "田野",
            "雨", "风", "火", "树", "鸟", "城市", "人群", "市场", "广场", "河", "溪", "海", "湖",
            "outdoor", "nature", "forest", "city", "crowd", "market", "river", "sea", "fire",
        )
        battle_keywords = (
            "战斗", "打斗", "战场", "爆炸", "枪", "剑", "刀", "搏斗", "追杀", "冲锋",
            "battle", "combat", "fight", "war", "explosion",
        )
        travel_keywords = (
            "车", "船", "火车", "列车", "马车", "飞机", "旅途", "路途", "旅行", "赶路",
            "行驶", "驶过", "travel", "train", "car", "ship", "plane", "road",
        )
        mystery_keywords = (
            "侦探", "谜", "秘密", "暗号", "阴谋", "诡", "线索", "悬疑", "神秘",
            "mystery", "secret", "clue", "detective",
        )
        romance_keywords = (
            "爱情", "拥抱", "亲吻", "婚礼", "温柔", "romance", "love", "kiss", "wedding",
        )
        horror_keywords = (
            "恐怖", "惊悚", "诡异", "阴森", "鬼", "幽灵", "怪物", "nightmare", "horror",
        )

        if any(key in text for key in indoor_keywords):
            add("indoor")
        if any(key in text for key in outdoor_keywords):
            add("outdoor")
        if any(key in text for key in battle_keywords):
            add("battle")
        if any(key in text for key in travel_keywords):
            add("travel")
        if any(key in text for key in mystery_keywords):
            add("mystery")
        if any(key in text for key in romance_keywords):
            add("romance")
        if any(key in text for key in horror_keywords):
            add("horror")

        if not scenes:
            if effect_type == EffectType.ENVIRONMENT:
                add("outdoor")
            else:
                add("general")

        return scenes

    def _infer_effect_type_from_description(self, description: str) -> EffectType:
        text = str(description or "")
        if any(key in text for key in ("雨", "风", "森林", "街道", "人群", "环境", "水流", "火焰", "海浪")):
            return EffectType.ENVIRONMENT
        if any(key in text for key in ("转场", "闪回", "回忆", "过渡")):
            return EffectType.TRANSITION
        if any(key in text for key in ("心跳", "呼吸", "嗡", "低鸣", "耳鸣", "尖啸", "回声")):
            return EffectType.EMOTION
        return EffectType.ACTION

    def _build_generated_effect_classification(
        self,
        *,
        description: str,
        effect_type: EffectType,
        scene_id: str = "",
        mood: str = "",
        category_hint: str = "",
        style_hint: str = "",
    ) -> Dict[str, Any]:
        category = self._normalize_effect_category(category_hint or effect_type.value, default=effect_type.value)
        style = self._normalize_effect_style(
            style_hint or self._infer_effect_style_from_description(description, effect_type, mood=mood),
            default="realistic",
        )
        scenes = self._infer_usage_scenes_from_description(description, effect_type)
        if scene_id and scene_id not in scenes and scene_id != "ambient":
            scenes.append(scene_id)
        tags = [category, style, *scenes]
        return {
            "category": category,
            "style": style,
            "scenes": scenes,
            "tags": list(dict.fromkeys(tag for tag in tags if tag)),
        }
    
    def design_ambient_sound(
        self,
        scene_description: str,
        duration: float
    ) -> SoundEffectCue:
        """设计环境音（支持 LLM 智能场景分析 + 关键词映射混合模式）

        Args:
            scene_description: 场景描述，如"雨夜的城市街道"
            duration: 持续时长（秒）

        Returns:
            环境音效提示
        """
        logger.info(f"🌆 设计环境音: {scene_description}")

        # 1. 尝试使用 LLM 智能分析
        if self.llm_client:
            effect_name = self._llm_match_effect(scene_description)
            if effect_name and effect_name in self.sound_library:
                logger.info(f"✅ LLM 智能匹配到音效: {effect_name}")
            else:
                # LLM 未命中，降级到关键词映射
                logger.info(f"⚠️ LLM 未匹配到音效，降级到关键词映射")
                effect_name = self._keyword_match_effect(scene_description)
        else:
            # 无 LLM，直接使用关键词映射
            effect_name = self._keyword_match_effect(scene_description)

        effect_info = self.sound_library.get(effect_name, {})

        cue = SoundEffectCue(
            scene_id="ambient",
            timestamp=0.0,
            effect_type=EffectType.ENVIRONMENT,
            description=scene_description,
            audio_file=effect_info.get("file", "ambient.mp3"),
            volume=0.2,  # 环境音音量较低
            fade_in=3.0,
            fade_out=3.0,
            loop=True,
            duration=duration,
            mix_mode="background",
            effect_id=effect_name,
        )

        return cue

    def _run_llm_chat_sync(self, prompt: str, max_tokens: int) -> str:
        return call_audiobook_llm_sync(
            self.llm_client,
            messages=[{"role": "user", "content": prompt}],
            task_type=TaskType.AUDIOBOOK_SOUND,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            use_cache=True,
            timeout_seconds=30,
        )

    def _llm_match_effect(self, scene_description: str) -> Optional[str]:
        """使用 LLM 智能匹配音效
        
        Args:
            scene_description: 场景描述
            
        Returns:
            匹配的音效 ID，或 None 表示未匹配
        """
        try:
            # 构建 prompt，让 LLM 分析场景氛围并推荐音效
            available_effects = list(self.sound_library.keys())
            prompt = f"""分析以下场景描述，从可用音效库中推荐最匹配的音效ID：

场景：{scene_description}

可用音效库：{available_effects}

要求：
- 只能从可用音效库中选择 effect_id，不要编造新 ID。
- 最多2个，优先选择最关键的动作或环境音。
- 只推荐音效，不要音乐，不要人声台词，不要旁白。
- 请直接返回 JSON 格式，如：{{"recommended": ["rain_heavy", "wind"]}}
- 只返回 JSON，不要其他内容。"""

            # 调用 LLM 分析
            if hasattr(self.llm_client, "chat"):
                response = self._run_llm_chat_sync(prompt, max_tokens=100)
            else:
                try:
                    response = self.llm_client.generate(
                        prompt,
                        max_tokens=100,
                        model=get_audiobook_llm_model(),
                    )
                except TypeError:
                    response = self.llm_client.generate(prompt, max_tokens=100)
            
            if not response:
                return None

            # 解析 LLM 返回结果
            result = parse_llm_json_object(response)
            recommended = result.get("recommended", [])
            
            if recommended:
                return recommended[0]
            
            return None

        except Exception as e:
            logger.warning(f"⚠️ LLM 音效匹配失败: {e}")
            return None

    def _keyword_match_effect(self, scene_description: str) -> str:
        """关键词映射匹配音效（降级方案）"""
        ambient_map = {
            "大雨": "rain_heavy",  # "大雨" 必须在 "雨" 之前
            "暴雨": "rain_heavy",
            "倾盆": "rain_heavy",
            "雨": "rain_light",
            "风": "wind",
            "城市": "city_ambient",
            "街道": "city_ambient",
            "森林": "forest_ambient",
            "林": "forest_ambient",
        }

        effect_name = "city_ambient"  # 默认
        for keyword, name in ambient_map.items():
            if keyword in scene_description:
                effect_name = name
                break

        return effect_name

    def _infer_mood_from_scene(self, scene_description: str) -> str:
        """根据场景文本粗略推断情绪标签（用于Mureka环境音）"""
        text = scene_description
        if any(k in text for k in ["紧张", "追杀", "追逐", "战斗", "惊悚", "血", "爆炸"]):
            return "tense"
        if any(k in text for k in ["兴奋", "热血", "欢呼", "比赛"]):
            return "exciting"
        if any(k in text for k in ["悲伤", "哭", "葬礼", "孤独", "失去"]):
            return "sad"
        if any(k in text for k in ["浪漫", "约会", "拥抱", "亲吻"]):
            return "romantic"
        if any(k in text for k in ["史诗", "大战", "军队", "王朝", "决战"]):
            return "epic"
        return "calm"

    def _build_ambient_effect_metadata(
        self,
        scene_description: str,
        mood: str,
        provider: str = "Mureka",
    ) -> Dict[str, Any]:
        """从场景描述构造环境音的ID/目录/标签等元数据"""
        text = scene_description
        base = "city"
        label = "ambient"
        tags: List[str] = []

        if any(k in text for k in ["森林", "林间", "树林"]):
            base = "forest"
            tags.append("森林")
        elif any(k in text for k in ["山", "山崖", "山谷"]):
            base = "mountain"
            tags.append("山")
        elif any(k in text for k in ["海", "海边", "海岸", "沙滩"]):
            base = "sea"
            tags.append("海")
        elif any(k in text for k in ["乡村", "田野"]):
            base = "country"
            tags.append("乡村")
        else:
            base = "city"
            if any(k in text for k in ["街", "路", "巷"]):
                tags.append("城市")

        if "雨" in text:
            label = "rain"
            tags.append("雨")
        elif "风" in text:
            label = "wind"
            tags.append("风")
        elif any(k in text for k in ["人群", "市场", "广场"]):
            label = "crowd"
            tags.append("人群")

        mood_tag = mood or "calm"
        tags.append(mood_tag)
        if provider:
            tags.append(provider)

        slug = f"{base}_{label}"
        raw = f"{scene_description}|{mood_tag}|{provider}"
        short_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()[:6]
        provider_suffix = provider.lower() if provider else "generic"
        effect_id = f"ambient_{slug}_{mood_tag}_{provider_suffix}_{short_hash}"

        # 子目录，例如 environment/city_rain
        subdir = slug

        # 显示名称（中文友好）
        if base == "forest":
            base_cn = "森林"
        elif base == "mountain":
            base_cn = "山景"
        elif base == "sea":
            base_cn = "海边"
        elif base == "country":
            base_cn = "乡村"
        else:
            base_cn = "城市"

        if label == "rain":
            label_cn = "雨夜"
        elif label == "wind":
            label_cn = "风声"
        elif label == "crowd":
            label_cn = "人群"
        else:
            label_cn = "环境"

        name = f"{base_cn}{label_cn}环境音（{provider}，{mood_tag}）"

        return {
            "effect_id": effect_id,
            "subdir": subdir,
            "tags": tags,
            "name": name,
        }

    def _get_music_generator(self) -> Optional[AIMusicGenerator]:
        """懒加载 Mureka AI 音乐生成器，用于通用环境音生成"""
        if self._music_generator is None:
            try:
                self._music_generator = create_music_generator(enable_cache=True)
            except Exception as e:
                logger.warning(f"⚠️ 初始化 Mureka 音乐生成器失败: {e}")
                self._music_generator = None
        return self._music_generator

    def _resolve_effect_audio_path(self, file_ref: str) -> Optional[Path]:
        """解析音效文件引用，返回存在的本地路径。"""
        raw = str(file_ref or "").strip()
        if not raw or raw == "placeholder.mp3":
            return None

        path = Path(raw)
        if path.is_absolute():
            return path if path.exists() else None

        candidates = [
            AUDIO_LIBRARY_DIR / path,
            SOUND_EFFECTS_DIR / path,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

        stem = path.stem
        if stem and SOUND_EFFECTS_DIR.exists():
            for candidate in SOUND_EFFECTS_DIR.rglob(f"{stem}.*"):
                if candidate.exists():
                    return candidate

        return None

    def _has_resolvable_audio_file(self, file_ref: str) -> bool:
        return self._resolve_effect_audio_path(file_ref) is not None

    async def ensure_generated_assets(
        self,
        max_generated_effects: int = 5,
    ) -> None:
        """为当前音效时间线补齐缺失的真实音频素材。"""
        if not self.effect_cues:
            return

        remaining = max(0, int(max_generated_effects)) or 0
        if remaining <= 0:
            return

        for index, cue in enumerate(list(self.effect_cues)):
            if remaining <= 0:
                return
            if self._has_resolvable_audio_file(cue.audio_file):
                continue

            effect_type = getattr(cue.effect_type, "value", str(cue.effect_type))
            if effect_type != EffectType.ENVIRONMENT.value:
                continue

            try:
                replacement = await self.ensure_vidu_ambient_sound(
                    cue.description,
                    cue.duration or 10.0,
                    mood=self._infer_mood_from_scene(cue.description),
                )
            except Exception as exc:
                logger.warning("⚠️ 生成环境音素材失败（忽略并继续）: %s", exc)
                continue

            if not replacement or not self._has_resolvable_audio_file(replacement.audio_file):
                continue

            replacement.scene_id = cue.scene_id
            replacement.timestamp = cue.timestamp
            replacement.volume = cue.volume
            replacement.fade_in = cue.fade_in
            replacement.fade_out = cue.fade_out
            replacement.duration = cue.duration
            replacement.mix_mode = cue.mix_mode
            self.effect_cues[index] = replacement
            remaining -= 1

        if remaining > 0:
            await self.enhance_effects_with_vidu(max_vidu_effects=remaining)

    async def ensure_mureka_ambient_sound(
        self,
        scene_description: str,
        duration: float,
        mood: Optional[str] = None,
    ) -> SoundEffectCue:
        """本地优先 + Mureka 兜底 的环境音设计器

        1. 优先在现有音效库（含本地索引 + Mureka 生成并入库的环境音）中查找。
        2. 若未找到合适环境音，则调用 Mureka 生成一段氛围音乐，写入本地 sound_effects 仓库和索引。
        3. 返回可直接用于混音的 SoundEffectCue。
        """
        logger.info(f"🌆 [Mureka] 设计环境音: {scene_description}")

        # 1. 尝试使用现有音效库匹配环境音（包括已入库的Mureka环境音）
        local_cue = self._match_effect(
            description=scene_description,
            timestamp=0.0,
            scene_id="ambient",
        )
        if (
            local_cue
            and local_cue.effect_type == EffectType.ENVIRONMENT
            and self._has_resolvable_audio_file(local_cue.audio_file)
        ):
            # 调整为环境层参数
            local_cue.description = scene_description
            local_cue.timestamp = 0.0
            local_cue.loop = True
            local_cue.duration = duration
            local_cue.volume = 0.2
            local_cue.fade_in = 3.0
            local_cue.fade_out = 3.0
            local_cue.mix_mode = "background"
            logger.info("✅ 使用本地环境音，无需调用 Mureka")
            return local_cue

        # 2. 调用 Mureka 生成新的环境音
        music_generator = self._get_music_generator()
        if not music_generator:
            logger.warning("⚠️ 未能初始化 Mureka 音乐生成器，回退到内置环境音逻辑")
            return self.design_ambient_sound(scene_description, duration)

        mood_value = mood or self._infer_mood_from_scene(scene_description)
        try:
            music_result: MusicGenerationResult = await music_generator.generate_for_scene(
                scene_description=scene_description,
                mood=mood_value,
                duration=int(duration) if duration > 0 else 30,
            )
        except Exception as e:
            logger.warning(f"⚠️ 调用 Mureka 生成环境音失败: {e}，回退到内置环境音")
            return self.design_ambient_sound(scene_description, duration)

        if not music_result.success or not music_result.audio_file_path:
            logger.warning("⚠️ Mureka 返回的环境音结果无效，回退到内置环境音")
            return self.design_ambient_sound(scene_description, duration)

        # 3. 将 Mureka 结果写入本地 sound_effects 仓库 + 索引
        meta = self._build_ambient_effect_metadata(scene_description, mood_value, provider="Mureka")
        effect_id = meta["effect_id"]
        subdir = meta["subdir"]
        tags = meta["tags"]
        name = meta["name"]
        classification = self._build_generated_effect_classification(
            description=scene_description,
            effect_type=EffectType.ENVIRONMENT,
            scene_id="ambient",
            mood=mood_value,
            category_hint="environment",
            style_hint="peaceful" if mood_value in {"calm", "sad", "romantic", "peaceful"} else "realistic",
        )

        source_path = Path(music_result.audio_file_path)
        ext = source_path.suffix or ".mp3"
        relative_dir = Path("environment") / subdir
        output_dir = SOUND_EFFECTS_DIR / relative_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{effect_id}{ext}"

        try:
            shutil.copy(source_path, output_file)
        except Exception as e:
            logger.warning(f"⚠️ 拷贝 Mureka 环境音文件失败: {e}，回退到内置环境音")
            return self.design_ambient_sound(scene_description, duration)

        # file_path 相对于 AUDIO_LIBRARY_DIR，供后续组合路径使用
        relative_file_path = str(Path("sound_effects") / relative_dir / output_file.name).replace(os.sep, "/")

        record: Dict[str, Any] = {
            "id": effect_id,
            "name": name,
            "category": f"{classification['category']}/{classification['style']}",
            "file_path": relative_file_path,
            "description": scene_description,
            "tags": list(dict.fromkeys([*tags, *classification["tags"]])),
            "source": "mureka",
            "style": classification["style"],
            "scenes": classification["scenes"],
        }
        self.register_new_effect(record)
        logger.info(f"🎧 已生成并注册 Mureka 环境音: {effect_id}")

        return SoundEffectCue(
            scene_id="ambient",
            timestamp=0.0,
            effect_type=EffectType.ENVIRONMENT,
            description=scene_description,
            audio_file=relative_file_path,
            volume=0.2,
            fade_in=3.0,
            fade_out=3.0,
            loop=True,
            duration=duration,
            mix_mode="background",
            effect_id=effect_id,
        )

    async def _generate_vidu_audio_for_prompt(
        self,
        *,
        prompt: str,
        duration: float,
        max_wait: int = 60,
    ):
        """把单段音效描述适配为 Vidu timing2audio 请求。"""
        if self._vidu_generator is None:
            raise RuntimeError("Vidu generator is not initialized")

        duration_sec = max(2.0, min(10.0, float(duration or 0)))
        timing_prompts = [
            {
                "from": 0.0,
                "to": duration_sec,
                "prompt": str(prompt or "").strip(),
            }
        ]
        return await self._vidu_generator.generate_audio_async(
            timing_prompts=timing_prompts,
            duration=duration_sec,
            max_wait=max_wait,
        )

    async def ensure_vidu_ambient_sound(
        self,
        scene_description: str,
        duration: float,
        mood: Optional[str] = None,
    ) -> SoundEffectCue:
        """使用ViduAI生成环境音（本地 + ViduAI兜底）"""
        logger.info(f"🌆 [ViduAI] 设计环境音: {scene_description}")

        # 初始化ViduAI生成器
        if self._vidu_generator is None:
            vidu_key = getattr(settings, "VIDU_API_KEY", "") or os.getenv("VIDU_API_KEY", "")
            if not vidu_key:
                logger.warning("⚠️ 未配置ViduAI API密钥(VIDU_API_KEY)，回退到 Mureka 环境音逻辑")
                return await self.ensure_mureka_ambient_sound(scene_description, duration, mood)
            self._vidu_generator = create_vidu_timing2audio_generator(api_key=vidu_key)

        # 1. 先尝试使用本地已生成的环境音
        local_cue = self._match_effect(
            description=scene_description,
            timestamp=0.0,
            scene_id="ambient",
        )
        if (
            local_cue
            and local_cue.effect_type == EffectType.ENVIRONMENT
            and self._has_resolvable_audio_file(local_cue.audio_file)
        ):
            local_cue.description = scene_description
            local_cue.timestamp = 0.0
            local_cue.loop = True
            local_cue.duration = duration
            local_cue.volume = 0.2
            local_cue.fade_in = 3.0
            local_cue.fade_out = 3.0
            local_cue.mix_mode = "background"
            logger.info("✅ 使用本地环境音，无需调用ViduAI")
            return local_cue

        # 2. 调用ViduAI生成新的环境音
        duration_sec = max(3.0, min(10.0, duration))
        
        # 将音效描述转换为简洁的中文 prompt（适合ViduAI）
        ambient_prompt = scene_description
        logger.info(f"🎧 [ViduAI] 环境音 prompt: {ambient_prompt} (时长: {duration_sec}s)")

        try:
            result = await self._generate_vidu_audio_for_prompt(
                prompt=ambient_prompt,
                duration=duration_sec,
                max_wait=60,
            )
            
            if not result.success:
                logger.warning(f"⚠️ ViduAI环境音生成失败: {result.error}，回退到 Mureka/内置环境音")
                return await self.ensure_mureka_ambient_sound(scene_description, duration, mood)
            
            audio_url = result.audio_url
            if not audio_url:
                logger.warning("⚠️ ViduAI返回结果中缺少音频URL，回退到 Mureka/内置环境音")
                return await self.ensure_mureka_ambient_sound(scene_description, duration, mood)

            # 3. 下载ViduAI返回的音频并写入本地 sound_effects 仓库 + 索引
            mood_value = mood or self._infer_mood_from_scene(scene_description)
            meta = self._build_ambient_effect_metadata(scene_description, mood_value, provider="Vidu")
            effect_id = meta["effect_id"]
            tags = meta["tags"]
            name = meta["name"]
            classification = self._build_generated_effect_classification(
                description=scene_description,
                effect_type=EffectType.ENVIRONMENT,
                scene_id="ambient",
                mood=mood_value,
                category_hint="environment",
                style_hint="peaceful" if mood_value in {"calm", "sad", "romantic", "peaceful"} else "realistic",
            )

            category = f"{classification['category']}/{classification['style']}"
            record = self.download_and_register_effect(
                url=audio_url,
                effect_id=effect_id,
                category=category,
                description=name,
                tags=list(dict.fromkeys([*tags, *classification["tags"]])),
                source="vidu",
                style=classification["style"],
                scenes=classification["scenes"],
            )
            if not record:
                logger.warning("⚠️ ViduAI环境音下载或注册失败，回退到 Mureka/内置环境音")
                return await self.ensure_mureka_ambient_sound(scene_description, duration, mood)

            logger.info(f"🎧 已生成并注册ViduAI环境音: {effect_id}")

            return SoundEffectCue(
                scene_id="ambient",
                timestamp=0.0,
                effect_type=EffectType.ENVIRONMENT,
                description=scene_description,
                audio_file=record.get("file_path", ""),
                volume=0.2,
                fade_in=3.0,
                fade_out=3.0,
                loop=True,
                duration=duration,
                mix_mode="background",
                effect_id=effect_id,
            )
            
        except Exception as e:
            logger.warning(f"⚠️ 调用ViduAI生成环境音失败: {e}，回退到 Mureka/内置环境音")
            return await self.ensure_mureka_ambient_sound(scene_description, duration, mood)

    async def enhance_effects_with_vidu(
        self,
        max_vidu_effects: int = 5,
    ) -> None:
        """使用ViduAI为占位音效生成真实音效（仅 ACTION/EMOTION 类型）

        设计原则：
        1. 只处理当前时间线中 audio_file 为空或 placeholder.mp3 的提示；
        2. 只处理 ACTION / EMOTION 两类短效音，避免误当作整章环境床；
        3. 为每个描述生成一段 1-5 秒的短音效，并入库，后续可被 _match_effect 命中。
        """
        if not self.effect_cues:
            return

        # 初始化ViduAI生成器
        if self._vidu_generator is None:
            vidu_key = getattr(settings, "VIDU_API_KEY", "") or os.getenv("VIDU_API_KEY", "")
            if not vidu_key:
                logger.info("⚠️ 未配置ViduAI API密钥(VIDU_API_KEY)，跳过占位音效增强")
                return
            self._vidu_generator = create_vidu_timing2audio_generator(api_key=vidu_key)

        remaining = max(0, int(max_vidu_effects)) or 0
        if remaining <= 0:
            return

        try:
            for cue in self.effect_cues:
                if remaining <= 0:
                    break

                # 仅处理缺失或占位音效；本地能解析的文件不重复生成
                if self._has_resolvable_audio_file(cue.audio_file):
                    continue

                # 仅处理动作/情绪类短效音
                if cue.effect_type not in (EffectType.ACTION, EffectType.EMOTION):
                    continue

                try:
                    record = await self._generate_vidu_effect_for_cue(cue)
                    if record and record.get("file_path"):
                        cue.audio_file = record["file_path"]
                        cue.effect_id = str(record.get("id") or cue.effect_id or "")
                        remaining -= 1
                except Exception as e:
                    logger.warning(f"⚠️ 使用ViduAI生成音效失败（忽略并继续）: {e}")
                    continue
        except Exception as e:
            logger.warning(f"⚠️ 占位音效ViduAI增强流程失败: {e}")

    async def _generate_vidu_effect_for_cue(
        self,
        cue: SoundEffectCue,
    ) -> Optional[Dict[str, Any]]:
        """针对单个占位音效，调用ViduAI生成短音效并入库。"""
        # 动作音一般更短，情绪音稍长一些
        base_duration = 3 if cue.effect_type == EffectType.ACTION else 5
        duration_sec = max(3.0, min(base_duration, 10.0))

        logger.info(f"🎧 [ViduAI] 为占位音效生成短音效: {cue.description} ({cue.effect_type.value})")

        effect_prompt = self._build_vidu_effect_prompt(cue)
        logger.info(f"🎧 [ViduAI] 短音效 prompt: {effect_prompt} (时长: {duration_sec}s)")

        try:
            result = await self._generate_vidu_audio_for_prompt(
                prompt=effect_prompt,
                duration=duration_sec,
                max_wait=60,
            )
            
            if not result.success:
                logger.warning(f"⚠️ ViduAI短音效生成失败: {result.error}")
                return None
            
            audio_url = result.audio_url
            if not audio_url:
                logger.warning("⚠️ ViduAI短音效结果中缺少音频URL")
                return None

            # 构造元数据并入库
            raw = f"{cue.description}|{cue.effect_type.value}|Vidu"
            short_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()[:6]
            effect_id = f"sfx_{cue.effect_type.value}_{short_hash}"
            description = cue.description or f"{cue.effect_type.value} effect"
            classification = self._build_generated_effect_classification(
                description=description,
                effect_type=cue.effect_type,
                scene_id=cue.scene_id,
                mood=self._infer_mood_from_scene(description),
                category_hint=cue.effect_type.value,
            )

            record = self.download_and_register_effect(
                url=audio_url,
                effect_id=effect_id,
                category=f"{classification['category']}/{classification['style']}",
                description=description,
                tags=classification["tags"],
                source="vidu",
                style=classification["style"],
                scenes=classification["scenes"],
            )
            if not record:
                logger.warning("⚠️ ViduAI短音效下载或注册失败")
                return None

            logger.info(f"🎧 已生成并注册ViduAI短音效: {effect_id}")
            return record
            
        except Exception as e:
            logger.warning(f"⚠️ ViduAI短音效生成异常: {e}")
            return None

    def _build_vidu_effect_prompt(self, cue: SoundEffectCue) -> str:
        """把剧本里的短音效名称扩展成更明确的生成提示。"""
        description = str(getattr(cue, "description", "") or "").strip()
        if not description:
            description = f"{cue.effect_type.value} sound effect"

        enrichments = []
        for keywords, prompt_text in EFFECT_PROMPT_ENRICHMENTS:
            if any(keyword in description for keyword in keywords):
                enrichments.append(prompt_text)

        layer_hint = "短促触发式动作音效"
        if cue.effect_type == EffectType.EMOTION:
            layer_hint = "情绪氛围短音效"
        elif cue.effect_type == EffectType.TRANSITION:
            layer_hint = "转场短音效"

        parts = [description]
        if enrichments:
            parts.append("声音设计：" + "；".join(dict.fromkeys(enrichments)))
        parts.append(f"类型：{layer_hint}")
        parts.append("只生成音效，不要音乐，不要人声台词，不要旁白")
        return "。".join(part.strip("。") for part in parts if part).strip()

    def optimize_effect_density(
        self,
        max_effects_per_minute: int = 6
    ) -> List[SoundEffectCue]:
        """
        优化音效密度（避免过载）
        
        Args:
            max_effects_per_minute: 每分钟最大音效数
        
        Returns:
            优化后的音效列表
        """
        logger.info("🔧 优化音效密度...")
        
        if not self.effect_cues:
            return []
        
        try:
            max_per_minute = float(max_effects_per_minute or 6)
        except (TypeError, ValueError):
            max_per_minute = 6.0
        max_per_minute = max(1.0, min(60.0, max_per_minute))
        min_interval_seconds = 60.0 / max_per_minute

        # 按时间排序
        sorted_cues = sorted(self.effect_cues, key=lambda x: x.timestamp)
        
        # 检查密度
        optimized_cues = []
        last_timestamp = -999
        
        for cue in sorted_cues:
            # 根据密度配置控制动作/情绪/转场音效间隔；环境床不参与短效密度限制。
            if cue.effect_type == EffectType.ENVIRONMENT:
                optimized_cues.append(cue)
            elif cue.timestamp - last_timestamp >= min_interval_seconds:
                optimized_cues.append(cue)
                last_timestamp = cue.timestamp
            else:
                logger.debug(f"   跳过过密音效: {cue.description} at {cue.timestamp}s")
        
        logger.info(f"   ✅ 优化完成: {len(sorted_cues)} → {len(optimized_cues)} 个音效")
        
        self.effect_cues = optimized_cues
        return optimized_cues
    
    def export_effect_timeline(self) -> Dict[str, Any]:
        """导出音效时间线（用于混音）"""
        unresolved_effects = self._collect_unresolved_effects()
        timeline = {
            "total_effects": len(self.effect_cues),
            "effects_by_type": self._count_by_type(),
            "timeline": [
                {
                    "scene_id": cue.scene_id,
                    "timestamp": cue.timestamp,
                    "type": cue.effect_type.value,
                    "description": cue.description,
                    "file": cue.audio_file,
                    "volume": cue.volume,
                    "duration": cue.duration,
                    "fade_in": cue.fade_in,
                    "fade_out": cue.fade_out,
                    "loop": cue.loop,
                    "mix_mode": cue.mix_mode,
                    "effect_id": cue.effect_id,
                }
                for cue in sorted(self.effect_cues, key=lambda x: x.timestamp)
            ]
        }
        if unresolved_effects["unresolved_count"] > 0:
            count = unresolved_effects["unresolved_count"]
            timeline["unresolved_effects"] = unresolved_effects
            timeline["warnings"] = [
                {
                    "code": "unresolved_sound_effect_assets",
                    "level": "warning",
                    "message": f"有 {count} 个音效未找到真实素材，已在混音时跳过。",
                }
            ]
        
        return timeline

    def _collect_unresolved_effects(self) -> Dict[str, Any]:
        """统计无法解析为真实素材的音效，供前端质量报告展示。"""
        items: List[Dict[str, Any]] = []
        placeholder_count = 0
        missing_file_count = 0

        for cue in sorted(self.effect_cues, key=lambda x: x.timestamp):
            file_ref = str(cue.audio_file or "").strip()
            if file_ref and self._has_resolvable_audio_file(file_ref):
                continue

            if file_ref == "placeholder.mp3":
                reason = "placeholder_audio"
                placeholder_count += 1
            else:
                reason = "missing_audio_file"
                missing_file_count += 1

            items.append(
                {
                    "scene_id": cue.scene_id,
                    "timestamp": cue.timestamp,
                    "type": cue.effect_type.value,
                    "description": cue.description,
                    "file": file_ref,
                    "effect_id": cue.effect_id,
                    "reason": reason,
                }
            )

        return {
            "unresolved_count": len(items),
            "placeholder_count": placeholder_count,
            "missing_file_count": missing_file_count,
            "items": items,
        }
    
    def _count_by_type(self) -> Dict[str, int]:
        """按类型统计"""
        counts = {
            "environment": 0,
            "action": 0,
            "emotion": 0,
            "transition": 0
        }
        for cue in self.effect_cues:
            counts[cue.effect_type.value] += 1
        return counts
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_effects": len(self.effect_cues),
            "effects_by_type": self._count_by_type(),
            "sound_library_size": len(self.sound_library),
        }

    async def ai_match_effects(self, scene_text: str) -> List[str]:
        """AI智能匹配音效ID列表

        根据场景文本和当前音效库，调用LLM推荐合适的音效ID列表。
        """
        if not self.llm_client:
            logger.warning("⚠️ 未配置 llm_client，ai_match_effects 将返回空结果")
            return []

        available_effects = list(self.sound_library.keys())
        prompt = f"""
分析以下场景，基于可用音效库推荐最合适的音效 ID 列表。

场景内容:
{scene_text}

可选音效库（effect_id 列表）:
{available_effects}

请只输出 JSON，格式如下（不要添加多余文字）:
{{
  "effects": ["effect_id1", "effect_id2"]
}}
""".strip()

        try:
            # 使用有声小说专用任务类型，自动选择合适模型
            response = await call_audiobook_llm_async(
                self.llm_client,
                messages=[{"role": "user", "content": prompt}],
                task_type=TaskType.AUDIOBOOK_SOUND,
                use_cache=False,
            )
        except Exception as e:
            logger.warning(f"⚠️ 调用 LLM 进行音效匹配失败: {e}")
            return []

        # 尝试从响应中提取 JSON
        try:
            data = parse_llm_json_object(response)
            effects = data.get("effects", [])
            if not isinstance(effects, list):
                return []
            # 只保留在当前音效库中的 ID
            return [e for e in effects if isinstance(e, str) and e in self.sound_library]
        except Exception as e:
            logger.warning(f"⚠️ 解析 AI 音效匹配结果失败: {e}")
            return []
    
    def _load_external_sound_library(self) -> None:
        """从外部索引加载音效库

        支持的索引格式：
        - JSON 数组：[ {"id": ..., "category": ..., "file_path": ..., "description": ...}, ... ]
        - JSON 对象：{"id": { ...record... }}
        """
        index_path = self.index_path
        if not index_path or not index_path.exists():
            return
        
        try:
            with index_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 兼容数组或字典两种格式
            if isinstance(data, dict):
                records = list(data.values())
            else:
                records = list(data)
            
            loaded = 0
            for item in records:
                effect_id = item.get("id") or item.get("name")
                if not effect_id:
                    continue
                category = self._normalize_effect_category(item.get("category") or item.get("type") or "action")
                
                file_path = item.get("file_path") or item.get("file")
                description = item.get("description") or item.get("name") or effect_id
                
                if not file_path:
                    continue

                if not self._external_sound_file_exists(file_path):
                    logger.warning("⚠️ 音效索引条目文件不存在: %s", file_path)
                    continue

                existing = self.sound_library.get(effect_id)
                if existing and self._external_sound_file_exists(existing.get("file", "")):
                    continue
                
                self.sound_library[effect_id] = {
                    "type": category,
                    "file": file_path,
                    "description": description,
                    "tags": item.get("tags", []),
                    "source": item.get("source", "manual"),
                }
                loaded += 1
            
            if loaded:
                logger.info(f"🔊 从外部音效索引加载 {loaded} 个音效: {index_path}")
        except Exception as e:
            logger.warning(f"⚠️ 加载音效索引失败: {e}")

    def _external_sound_file_exists(self, file_ref: str) -> bool:
        """验证索引条目的文件引用是否可解析到本地素材。"""
        raw = str(file_ref or "").strip()
        if not raw:
            return False

        path = Path(raw)
        if path.is_absolute():
            return path.exists()

        return (
            (self.audio_library_dir / path).exists()
            or (self.sound_effects_dir / path).exists()
            or (AUDIO_LIBRARY_DIR / path).exists()
            or (SOUND_EFFECTS_DIR / path).exists()
        )
    
    def _assess_audio_quality(self, file_path: str) -> Dict[str, Any]:
        """评估音效文件质量，返回质量元数据。

        使用 pydub 检测关键指标：响度、削波、静音比例、时长。
        返回 {"quality_score": float, "quality_grade": str, "quality_status": str}
        """
        result = {"quality_score": 0.0, "quality_grade": "D", "quality_status": "rejected"}
        try:
            resolved = Path(file_path)
            if not resolved.is_absolute():
                resolved = self.audio_library_dir / file_path
            if not resolved.exists():
                return result

            from pydub import AudioSegment
            audio = AudioSegment.from_file(str(resolved))

            duration_s = len(audio) / 1000.0
            dbfs = audio.dBFS
            silent_ms = len(audio) - len(audio.strip_silence(silence_thresh=-50))
            silent_ratio = silent_ms / max(len(audio), 1)

            result = self._score_audio_quality_metrics(
                duration_s=duration_s,
                dbfs=dbfs,
                silent_ratio=silent_ratio,
            )
        except Exception as e:
            logger.debug("pydub 音效质量评估失败，尝试 ffmpeg 兜底 (%s): %s", file_path, e)
            result = self._assess_audio_quality_with_ffmpeg(resolved)
        return result

    def _score_audio_quality_metrics(
        self,
        *,
        duration_s: float,
        dbfs: float,
        silent_ratio: float = 0.0,
    ) -> Dict[str, Any]:
        score = 100.0

        if dbfs < -40.0:
            score -= 30
        elif dbfs < -30.0:
            score -= 15

        if silent_ratio > 0.8:
            score -= 40
        elif silent_ratio > 0.5:
            score -= 20

        score = max(0.0, min(100.0, score))

        if score >= 75:
            grade, status = "B", "accepted"
        elif score >= 60:
            grade, status = "C", "accepted"
        elif score >= 40:
            grade, status = "C", "tolerated"
        else:
            grade, status = "D", "rejected"

        return {"quality_score": round(score, 1), "quality_grade": grade, "quality_status": status}

    def _assess_audio_quality_with_ffmpeg(self, resolved: Path) -> Dict[str, Any]:
        fallback = {"quality_score": 0.0, "quality_grade": "D", "quality_status": "rejected"}
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-show_entries",
                    "stream=codec_type,sample_rate,channels",
                    "-of",
                    "json",
                    str(resolved),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            probe_data = json.loads(probe.stdout or "{}")
            streams = probe_data.get("streams") or []
            has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
            if not has_audio:
                return fallback

            duration_s = float((probe_data.get("format") or {}).get("duration") or 0.0)
            volume = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-i",
                    str(resolved),
                    "-af",
                    "volumedetect",
                    "-f",
                    "null",
                    "NUL" if os.name == "nt" else "/dev/null",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", volume.stderr or "")
            if not match:
                return fallback

            return self._score_audio_quality_metrics(
                duration_s=duration_s,
                dbfs=float(match.group(1)),
                silent_ratio=0.0,
            )
        except Exception as e:
            logger.debug("ffmpeg 音效质量评估失败 (%s): %s", resolved, e)
            return fallback

    def register_new_effect(self, record: Dict[str, Any]) -> None:
        """注册新的音效并写入索引

        典型用于 AI 生成音效后入库：
        record 示例：
        {
            "id": "forest_birds_ai_001",
            "name": "森林鸟鸣环境音（AI生成）",
            "category": "environment",
            "file_path": "sound_effects/generated/forest_birds_ai_001.mp3",
            "description": "森林里的鸟鸣声",
            "tags": ["森林", "鸟鸣"],
            "source": "ai"
        }
        """
        index_path = self.index_path
        try:
            file_path = record.get("file_path") or record.get("file", "")
            description = str(record.get("description") or record.get("name") or record.get("id") or "").strip()
            effect_type = self._coerce_effect_type(record.get("category") or record.get("type") or "action")
            normalized_category = self._normalize_effect_category(
                record.get("category") or effect_type.value,
                default=effect_type.value,
            )
            normalized_style = self._normalize_effect_style(
                record.get("style") or self._infer_effect_style_from_description(description, effect_type),
                default="realistic",
            )
            raw_scenes = record.get("scenes")
            if isinstance(raw_scenes, list):
                scenes = [str(item).strip() for item in raw_scenes if str(item).strip()]
            elif isinstance(raw_scenes, str):
                scenes = [item.strip() for item in raw_scenes.split(",") if item.strip()]
            else:
                scenes = self._infer_usage_scenes_from_description(description, effect_type)
            normalized_scenes = list(dict.fromkeys(scenes))
            existing_tags = []
            for tag in record.get("tags", []) or []:
                tag_text = str(tag).strip()
                if tag_text:
                    existing_tags.append(tag_text)
            record["category"] = f"{normalized_category}/{normalized_style}"
            record["style"] = normalized_style
            record["scenes"] = normalized_scenes
            record["tags"] = list(
                dict.fromkeys(
                    [*existing_tags, normalized_category, normalized_style, *normalized_scenes]
                )
            )
            quality = self._assess_audio_quality(file_path)
            record.setdefault("quality_score", quality["quality_score"])
            record.setdefault("quality_grade", quality["quality_grade"])
            record.setdefault("quality_status", quality["quality_status"])
            if record.get("quality_status") != "rejected":
                resolved_audio = self._resolve_effect_audio_path(file_path)
                if resolved_audio:
                    try:
                        record.update(
                            upload_audio_library_asset(
                                local_path=resolved_audio,
                                relative_path=str(file_path),
                                library_type="sfx",
                            )
                        )
                    except Exception as exc:
                        logger.warning("鈿狅笍 音效素材云端元数据写入失败，保留本地索引: %s", exc)

            records: List[Dict[str, Any]]
            if index_path.exists():
                with index_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    records = list(data.values())
                else:
                    records = list(data)
            else:
                index_path.parent.mkdir(parents=True, exist_ok=True)
                records = []
            
            effect_id = record.get("id")
            if effect_id:
                records = [r for r in records if r.get("id") != effect_id]
            records.append(record)
            
            with index_path.open("w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            
            if effect_id:
                category = self._normalize_effect_category(record.get("category", "action"))
                
                self.sound_library[effect_id] = {
                    "type": category,
                    "file": record.get("file_path") or record.get("file", ""),
                    "description": description or record.get("name", effect_id),
                    "tags": record.get("tags", []),
                    "style": record.get("style", ""),
                    "scenes": record.get("scenes", []),
                    "source": record.get("source", "ai"),
                    "quality_score": record.get("quality_score", 0.0),
                    "quality_grade": record.get("quality_grade", "D"),
                    "quality_status": record.get("quality_status", "rejected"),
                }

            self._upsert_generated_effect_to_db_index(record)

            status_tag = record.get("quality_status", "unknown")
            logger.info(f"✅ 新音效已注册并写入索引: {effect_id} (质量: {record.get('quality_grade', '?')} / {status_tag})")
        except Exception as e:
            logger.warning(f"⚠️ 写入音效索引失败: {e}")

    def _upsert_generated_effect_to_db_index(self, record: Dict[str, Any]) -> None:
        """同步共享数据库索引；失败不阻塞音效生成与本地索引写入。"""
        db = None
        try:
            db = SessionLocal()
            upsert_audio_library_asset(db, "sfx", record)
            db.commit()
        except Exception as exc:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.warning("⚠️ 音效素材数据库索引写入失败，保留本地索引: %s", exc)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

    def download_and_register_effect(
        self,
        url: str,
        effect_id: str,
        category: str,
        description: str,
        tags: Optional[List[str]] = None,
        file_name: Optional[str] = None,
        source: str = "manual",
        style: str = "",
        scenes: Optional[List[str]] = None,
        category_hint: str = "",
    ) -> Optional[Dict[str, Any]]:
        """从指定URL下载音效文件并注册到音效库索引中

        Args:
            url: 音效文件直链URL（应指向mp3/ogg等音频文件，而不是网页）
            effect_id: 在系统中使用的音效ID（如"door_wood_open_01"）
            category: 音效类别（如"environment/weather"、"action/door"）
            description: 人类可读的描述
            tags: 检索用标签列表
            file_name: 保存到本地的文件名（可选，不传则使用 effect_id + 源文件后缀）
            source: 来源标识（如"online_sfx"、"recorded"等）

        Returns:
            成功时返回完整的record字典，失败时返回None
        """
        try:
            # 下载文件
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()

            # 推断文件后缀
            ext = None
            if file_name and "." in file_name:
                ext = file_name.split(".")[-1]
            else:
                # 尝试从URL推断
                if "." in url.split("?")[0]:
                    ext = url.split("?")[0].rsplit(".", 1)[-1]
            if not ext:
                ext = "mp3"  # 默认使用mp3

            # 规范化文件名
            if not file_name:
                file_name = f"{effect_id}.{ext}"

            # category 作为相对目录，如 "environment/weather"
            relative_dir = Path(category.replace("\\", "/").replace("//", "/"))
            output_dir = SOUND_EFFECTS_DIR / relative_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / file_name

            with output_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # 构建记录并注册
            # file_path 相对于 AUDIO_LIBRARY_DIR，供后续组合路径使用
            relative_file_path = str(Path("sound_effects") / relative_dir / file_name).replace(os.sep, "/")
            effect_type = self._coerce_effect_type(category_hint or category or "action")
            classification = self._build_generated_effect_classification(
                description=description,
                effect_type=effect_type,
                scene_id="ambient" if "environment" in category else "",
                category_hint=category_hint or category or effect_type.value,
                style_hint=style,
            )
            merged_scenes = list(dict.fromkeys([*(scenes or []), *classification["scenes"]]))
            merged_tags = list(dict.fromkeys([*(tags or []), *classification["tags"], *merged_scenes]))
            record: Dict[str, Any] = {
                "id": effect_id,
                "name": description,
                "category": f"{classification['category']}/{classification['style']}",
                "file_path": relative_file_path,
                "description": description,
                "tags": merged_tags,
                "source": source,
                "style": classification["style"],
                "scenes": merged_scenes,
            }

            self.register_new_effect(record)
            logger.info(f"🎧 已下载并注册音效: {effect_id} ← {url}")
            return record
        except Exception as e:
            logger.warning(f"⚠️ 下载并注册音效失败: {e}")
            return None

    def purge_low_quality_assets(self, min_score: float = 40.0, dry_run: bool = False) -> Dict[str, Any]:
        """从索引和磁盘删除低质素材。

        Args:
            min_score: 低于此分数的条目将被删除（默认 40，即 quality_status=rejected）
            dry_run: 仅统计不实际删除

        Returns:
            {"purged_count": int, "freed_bytes": int, "details": [...]}
        """
        return self._purge_assets(
            predicate=lambda rec: self._is_low_quality_record(rec, min_score),
            dry_run=dry_run,
            label="低质素材",
        )

    def _is_low_quality_record(self, rec: Dict[str, Any], min_score: float) -> bool:
        """仅清理已有明确质量结论的低质条目，避免误删历史无质量元数据素材。"""
        if rec.get("quality_status") == "rejected":
            return True
        if "quality_score" not in rec:
            return False
        try:
            return float(rec.get("quality_score")) < min_score
        except (TypeError, ValueError):
            return False

    def purge_orphan_entries(self, dry_run: bool = False) -> Dict[str, Any]:
        """清理索引中文件已不存在的孤立条目。

        Args:
            dry_run: 仅统计不实际删除

        Returns:
            {"purged_count": int, "freed_bytes": int, "details": [...]}
        """
        return self._purge_assets(
            predicate=lambda rec: not self._external_sound_file_exists(
                rec.get("file_path") or rec.get("file", "")
            ),
            dry_run=dry_run,
            label="孤立条目",
        )

    def _purge_assets(
        self,
        predicate,
        dry_run: bool = False,
        label: str = "",
    ) -> Dict[str, Any]:
        """通用素材清理：按 predicate 筛选索引条目并删除索引记录 + 磁盘文件。"""
        index_path = self.index_path
        if not index_path or not index_path.exists():
            return {"purged_count": 0, "freed_bytes": 0, "details": []}

        try:
            with index_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                records = list(data.values())
            else:
                records = list(data)

            to_purge = [r for r in records if predicate(r)]
            to_keep = [r for r in records if not predicate(r)]

            details = []
            freed_bytes = 0
            purged_count = 0

            for rec in to_purge:
                entry_id = rec.get("id", "?")
                file_ref = rec.get("file_path") or rec.get("file", "")
                resolved = self._resolve_deletable_asset_path(file_ref)
                file_size = 0
                if resolved and resolved.exists():
                    file_size = resolved.stat().st_size
                    if not dry_run:
                        try:
                            resolved.unlink()
                        except OSError:
                            pass
                freed_bytes += file_size
                purged_count += 1
                details.append({"id": entry_id, "file": file_ref, "size": file_size})

                self.sound_library.pop(entry_id, None)

            if not dry_run and purged_count > 0:
                with index_path.open("w", encoding="utf-8") as f:
                    json.dump(to_keep, f, ensure_ascii=False, indent=2)

            logger.info(
                "🗑️ %s清理%s: 删除 %d 条, 释放 %d 字节%s",
                label,
                "（预演）" if dry_run else "",
                purged_count,
                freed_bytes,
                "" if dry_run else f", 索引剩余 {len(to_keep)} 条",
            )
            return {"purged_count": purged_count, "freed_bytes": freed_bytes, "details": details}
        except Exception as e:
            logger.warning("⚠️ 素材清理失败: %s", e)
            return {"purged_count": 0, "freed_bytes": 0, "details": [], "error": str(e)}

    def _resolve_deletable_asset_path(self, file_ref: str) -> Optional[Path]:
        """仅允许清理当前索引素材库目录内的文件。"""
        raw = str(file_ref or "").strip()
        if not raw:
            return None
        base_dir = self.audio_library_dir.resolve()
        path = Path(raw)
        candidate = path if path.is_absolute() else self.audio_library_dir / path
        try:
            resolved = candidate.resolve()
            resolved.relative_to(base_dir)
        except (OSError, ValueError):
            return None
        return resolved

