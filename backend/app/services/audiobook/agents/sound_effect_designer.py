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
import shutil
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
from app.services.audiobook.vidu_timing2audio_generator import ViduTiming2AudioGenerator, create_vidu_timing2audio_generator

logger = logging.getLogger(__name__)

# 音效资源与索引默认路径（相对 backend/ 计算）
BACKEND_DIR = Path(__file__).resolve().parents[4]
AUDIO_LIBRARY_DIR = BACKEND_DIR / "data" / "audio_library"
SOUND_EFFECTS_DIR = AUDIO_LIBRARY_DIR / "sound_effects"
DEFAULT_INDEX_PATH = AUDIO_LIBRARY_DIR / "sound_effects_index.json"

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
            "paper_rustle": {"type": "action", "file": "paper.mp3", "description": "纸张簌簌声"},
            "keyboard": {"type": "action", "file": "keyboard.mp3", "description": "键盘声"},
            
            # 情绪音
            "heartbeat": {"type": "emotion", "file": "heartbeat.mp3", "description": "心跳声"},
            "breath_heavy": {"type": "emotion", "file": "breath.mp3", "description": "沉重呼吸"},
            "gasp": {"type": "emotion", "file": "gasp.mp3", "description": "倒吸气"},
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
                # 匹配音效库
                effect_cue = self._match_effect(
                    description=effect_desc,
                    timestamp=current_time,
                    scene_id=f"scene_{i}"
                )
                
                if effect_cue:
                    effect_cues.append(effect_cue)
            
            # 估算片段时长（粗略）
            text_length = len(segment.get("text", ""))
            estimated_duration = text_length / 10  # 假设10字/秒
            current_time += estimated_duration
        
        self.effect_cues = effect_cues

        # 优化音效密度，避免过载
        optimized = self.optimize_effect_density()
        logger.info(f"   ✅ 设计完成: {len(effect_cues)} → {len(optimized)} 个音效提示（含密度优化）")
        
        return optimized
    
    def _match_effect(
        self,
        description: str,
        timestamp: float,
        scene_id: str
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
            effect_type = EffectType(effect_info["type"])
            file_path = effect_info["file"]
            return SoundEffectCue(
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
            )

        # 2. 描述+标签匹配
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0

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

            if score > best_score:
                best_score = score
                best_match = {"name": effect_name, "info": effect_info}

        if best_match and best_score > 0:
            effect_info = best_match["info"]
            effect_type = EffectType(effect_info["type"])
            file_path = effect_info["file"]
            return SoundEffectCue(
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
            )

        # 3. 未找到匹配，创建占位
        logger.warning(f"⚠️ 未找到音效: {description}，使用占位")
        return SoundEffectCue(
            scene_id=scene_id,
            timestamp=timestamp,
            effect_type=EffectType.ACTION,
            description=description,
            audio_file="placeholder.mp3",
            volume=0.3,
        )
    
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
            prompt = f"""分析以下场景描述，从可用音效库中推荐1-2个最匹配的音效ID：

场景：{scene_description}

可用音效库：{available_effects}

请直接返回 JSON 格式，如：{{"recommended": ["rain_heavy", "wind"]}}
只返回 JSON，不要其他内容。"""

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
        if local_cue and local_cue.effect_type == EffectType.ENVIRONMENT and local_cue.audio_file not in ("", "placeholder.mp3"):
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
            "category": "environment",
            "file_path": relative_file_path,
            "description": scene_description,
            "tags": tags,
            "source": "mureka",
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
            self._vidu_generator = create_vidu_generator(api_key=vidu_key)

        # 1. 先尝试使用本地已生成的环境音
        local_cue = self._match_effect(
            description=scene_description,
            timestamp=0.0,
            scene_id="ambient",
        )
        if local_cue and local_cue.effect_type == EffectType.ENVIRONMENT and local_cue.audio_file not in ("", "placeholder.mp3"):
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
            result = await self._vidu_generator.generate_effect_async(
                prompt=ambient_prompt,
                duration=duration_sec,
                max_wait=60
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
            subdir = meta["subdir"]
            tags = meta["tags"]
            name = meta["name"]

            category = f"environment/{subdir}"
            record = self.download_and_register_effect(
                url=audio_url,
                effect_id=effect_id,
                category=category,
                description=name,
                tags=tags,
                source="vidu",
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
            self._vidu_generator = create_vidu_generator(api_key=vidu_key)

        remaining = max(0, int(max_vidu_effects)) or 0
        if remaining <= 0:
            return

        try:
            for cue in self.effect_cues:
                if remaining <= 0:
                    break

                # 仅处理占位音效
                if cue.audio_file not in ("", "placeholder.mp3"):
                    continue

                # 仅处理动作/情绪类短效音
                if cue.effect_type not in (EffectType.ACTION, EffectType.EMOTION):
                    continue

                try:
                    record = await self._generate_vidu_effect_for_cue(cue)
                    if record and record.get("file_path"):
                        cue.audio_file = record["file_path"]
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

        # 将音效描述转换为简洁的中文 prompt
        effect_prompt = cue.description
        logger.info(f"🎧 [ViduAI] 短音效 prompt: {effect_prompt} (时长: {duration_sec}s)")

        try:
            result = await self._vidu_generator.generate_effect_async(
                prompt=effect_prompt,
                duration=duration_sec,
                max_wait=60
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
            category = f"effects/{cue.effect_type.value}"
            tags = [cue.effect_type.value, "Vidu"]
            description = cue.description or f"{cue.effect_type.value} effect"

            record = self.download_and_register_effect(
                url=audio_url,
                effect_id=effect_id,
                category=category,
                description=description,
                tags=tags,
                source="vidu",
            )
            if not record:
                logger.warning("⚠️ ViduAI短音效下载或注册失败")
                return None

            logger.info(f"🎧 已生成并注册ViduAI短音效: {effect_id}")
            return record
            
        except Exception as e:
            logger.warning(f"⚠️ ViduAI短音效生成异常: {e}")
            return None

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
        
        # 按时间排序
        sorted_cues = sorted(self.effect_cues, key=lambda x: x.timestamp)
        
        # 检查密度
        optimized_cues = []
        last_timestamp = -999
        
        for cue in sorted_cues:
            # 确保音效间隔至少10秒（除了环境音）
            if cue.effect_type == EffectType.ENVIRONMENT:
                optimized_cues.append(cue)
            elif cue.timestamp - last_timestamp >= 10.0:
                optimized_cues.append(cue)
                last_timestamp = cue.timestamp
            else:
                logger.debug(f"   跳过过密音效: {cue.description} at {cue.timestamp}s")
        
        logger.info(f"   ✅ 优化完成: {len(sorted_cues)} → {len(optimized_cues)} 个音效")
        
        self.effect_cues = optimized_cues
        return optimized_cues
    
    def export_effect_timeline(self) -> Dict[str, Any]:
        """导出音效时间线（用于混音）"""
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
                }
                for cue in sorted(self.effect_cues, key=lambda x: x.timestamp)
            ]
        }
        
        return timeline
    
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
                # 已存在则跳过，优先保留代码内置定义
                if effect_id in self.sound_library:
                    continue
                
                category = item.get("category") or item.get("type") or "action"
                # 🔧 规范化 category：将 "core/environment" -> "environment", "effects/action" -> "action"
                if "/" in category:
                    category = category.split("/")[-1]  # 取最后一部分
                
                file_path = item.get("file_path") or item.get("file")
                description = item.get("description") or item.get("name") or effect_id
                
                if not file_path:
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
            records: List[Dict[str, Any]]
            if index_path.exists():
                with index_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # 统一转成列表写回
                    records = list(data.values())
                else:
                    records = list(data)
            else:
                # 确保目录存在
                index_path.parent.mkdir(parents=True, exist_ok=True)
                records = []
            
            # 去重：按 id 覆盖旧记录
            effect_id = record.get("id")
            if effect_id:
                records = [r for r in records if r.get("id") != effect_id]
            records.append(record)
            
            with index_path.open("w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            
            # 同步更新内存中的 sound_library
            if effect_id:
                category = record.get("category", "action")
                # 🔧 规范化 category
                if "/" in category:
                    category = category.split("/")[-1]
                
                self.sound_library[effect_id] = {
                    "type": category,
                    "file": record.get("file_path") or record.get("file", ""),
                    "description": record.get("description") or record.get("name", effect_id),
                    "tags": record.get("tags", []),
                    "source": record.get("source", "ai"),
                }
            logger.info(f"✅ 新音效已注册并写入索引: {effect_id}")
        except Exception as e:
            logger.warning(f"⚠️ 写入音效索引失败: {e}")

    def download_and_register_effect(
        self,
        url: str,
        effect_id: str,
        category: str,
        description: str,
        tags: Optional[List[str]] = None,
        file_name: Optional[str] = None,
        source: str = "manual",
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
            record: Dict[str, Any] = {
                "id": effect_id,
                "name": description,
                "category": category,
                "file_path": relative_file_path,
                "description": description,
                "tags": tags or [],
                "source": source,
            }

            self.register_new_effect(record)
            logger.info(f"🎧 已下载并注册音效: {effect_id} ← {url}")
            return record
        except Exception as e:
            logger.warning(f"⚠️ 下载并注册音效失败: {e}")
            return None

