"""
AI音乐生成引擎 - 昆仑万维Mureka O1集成

核心功能：
1. 文本描述→音乐生成（30+风格）
2. 音色克隆、音乐续写
3. 智能缓存机制（降低API成本）
4. 情绪→风格映射
"""

import os
import logging
import json
import hashlib
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

import requests
from app.core.config import settings

logger = logging.getLogger(__name__)


class MusicStyle(str, Enum):
    """音乐风格枚举（Mureka O1支持的风格）"""
    POP = "流行"           # 流行音乐
    ROCK = "摇滚"          # 摇滚
    JAZZ = "爵士"          # 爵士
    CLASSICAL = "古典"     # 古典音乐
    CHINESE_STYLE = "国风" # 中国风
    ELECTRONIC = "电子"    # 电子音乐
    AMBIENT = "氛围"       # 氛围音乐
    ORCHESTRAL = "管弦乐"  # 管弦乐
    PIANO = "钢琴"         # 钢琴曲
    SUSPENSE = "悬疑"      # 悬疑配乐
    ROMANTIC = "浪漫"      # 浪漫情歌
    EPIC = "史诗"          # 史诗音乐
    FOLK = "民谣"          # 民谣
    SOUNDTRACK = "影视配乐" # 电影配乐


@dataclass
class MusicGenerationRequest:
    """音乐生成请求"""
    prompt: str                    # 文本描述，如"悬疑感的低频钢琴曲"
    style: MusicStyle = MusicStyle.AMBIENT  # 音乐风格
    duration: int = 30             # 时长（秒），建议15-60秒
    tempo: str = "medium"          # 节奏：slow/medium/fast
    mood: str = "calm"             # 情绪：calm/tense/exciting/sad/mysterious
    instruments: list = None       # 乐器列表，如["piano", "strings"]
    
    def __post_init__(self):
        if self.instruments is None:
            self.instruments = []


@dataclass
class MusicGenerationResult:
    """音乐生成结果"""
    success: bool
    audio_file_path: str = ""      # 生成的音频文件路径
    audio_data: bytes = None       # 音频字节流
    duration: float = 0.0          # 实际时长
    file_size: int = 0             # 文件大小
    cost: float = 0.0              # 本次调用成本
    cached: bool = False           # 是否使用缓存
    error_message: str = ""        # 错误信息


class MurekaO1Client:
    """
    昆仑万维Mureka O1客户端
    
    官方文档: https://www.kunlun.com/mureka-api-docs
    SDK安装: pip install mureka-sdk
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_cache: bool = True,
        cache_dir: str = "backend/data/audio_library/music_cache"
    ):
        """
        Args:
            api_key: Mureka API密钥（从环境变量MUREKA_API_KEY获取）
            enable_cache: 是否启用缓存
            cache_dir: 缓存目录
        """
        # 优先顺序：显式参数 > 环境变量 > 配置文件
        self.api_key = api_key or os.getenv("MUREKA_API_KEY") or getattr(settings, "MUREKA_API_KEY", None)
        self.api_base = os.getenv("MUREKA_API_URL") or getattr(settings, "MUREKA_API_URL", "https://api.mureka.ai")
        if not self.api_key:
            logger.warning("⚠️ MUREKA_API_KEY未设置，AI音乐生成将使用模拟模式")
        
        self.enable_cache = enable_cache
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir.parent / "music_index.json"
        
        # 成本统计
        self.total_requests = 0
        self.cache_hits = 0
        self.total_cost = 0.0
        
        logger.info(f"✅ MurekaO1客户端初始化完成 (cache={enable_cache})")
    
    async def generate_music(
        self,
        request: MusicGenerationRequest
    ) -> MusicGenerationResult:
        """
        生成音乐
        
        Args:
            request: 音乐生成请求
        
        Returns:
            音乐生成结果
        """
        # 1. 检查缓存
        if self.enable_cache:
            cached_result = self._get_cached_music(request)
            if cached_result:
                logger.info(f"✅ 使用缓存音乐: {request.prompt[:30]}...")
                self.cache_hits += 1
                return cached_result
        
        # 2. 调用API生成
        try:
            result = await self._call_mureka_api(request)
            
            # 3. 保存缓存
            if self.enable_cache and result.success:
                self._save_to_cache(request, result)
            
            self.total_requests += 1
            self.total_cost += result.cost
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 音乐生成失败: {e}")
            return MusicGenerationResult(
                success=False,
                error_message=str(e)
            )
    
    async def _call_mureka_api(
        self,
        request: MusicGenerationRequest
    ) -> MusicGenerationResult:
        """
        调用Mureka O1 API
        
        注意：这是示例实现，需要根据Mureka官方SDK调整
        """
        if not self.api_key:
            # 模拟模式（用于开发测试）
            return await self._simulate_generation(request)
        
        try:
            # TODO: 根据 Mureka 官方文档调整具体接口路径和参数
            # 这里提供一个基于 HTTP 的参考实现：
            base_url = self.api_base.rstrip("/")
            endpoint = f"{base_url}/v1/music/generate"

            payload = {
                "prompt": request.prompt,
                "style": request.style.value,
                "duration": request.duration,
                "tempo": request.tempo,
                "mood": request.mood,
                "instruments": request.instruments,
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            loop = asyncio.get_running_loop()

            def _do_request():
                resp = requests.post(endpoint, json=payload, headers=headers, timeout=300)
                resp.raise_for_status()
                return resp

            resp = await loop.run_in_executor(None, _do_request)

            # 假设接口返回 JSON，包含音频下载地址或直接的音频二进制
            content_type = resp.headers.get("Content-Type", "")
            audio_data: bytes
            duration = request.duration
            cost = 0.0

            if "application/json" in content_type:
                data = resp.json()
                audio_url = data.get("audio_url") or data.get("bgm_url")
                duration = data.get("duration", duration)
                cost = float(data.get("cost", 0.0))

                if not audio_url:
                    raise RuntimeError("Mureka 返回数据中缺少 audio_url 字段")

                def _download():
                    r2 = requests.get(audio_url, timeout=300)
                    r2.raise_for_status()
                    return r2.content

                audio_data = await loop.run_in_executor(None, _download)
            else:
                # 直接返回音频二进制（如 audio/mpeg）
                audio_data = resp.content

            # 将结果写入缓存目录的临时文件
            cache_key = self._get_cache_key(request)
            output_file = self.cache_dir / f"{cache_key}.mp3"
            with open(output_file, "wb") as f:
                f.write(audio_data)

            return MusicGenerationResult(
                success=True,
                audio_file_path=str(output_file),
                audio_data=audio_data,
                duration=duration,
                file_size=len(audio_data),
                cost=cost,
                cached=False,
            )

        except Exception as e:
            raise RuntimeError(f"Mureka API调用失败: {e}")
    
    async def _simulate_generation(
        self,
        request: MusicGenerationRequest
    ) -> MusicGenerationResult:
        """模拟音乐生成（用于测试）"""
        logger.info(f"🎵 模拟生成音乐: {request.prompt[:50]}...")
        
        # 模拟延迟
        await asyncio.sleep(0.5)
        
        # 生成占位音频（空字节流）
        audio_data = b"MUSIC_PLACEHOLDER"  # 实际应该是MP3字节流
        
        # 保存到临时文件
        output_file = self.cache_dir / f"simulated_{hash(request.prompt)}.mp3"
        with open(output_file, 'wb') as f:
            f.write(audio_data)
        
        return MusicGenerationResult(
            success=True,
            audio_file_path=str(output_file),
            audio_data=audio_data,
            duration=request.duration,
            file_size=len(audio_data),
            cost=0.0,  # 模拟模式免费
            cached=False
        )
    
    def _get_cache_key(self, request: MusicGenerationRequest) -> str:
        """生成缓存键"""
        # 基于请求参数生成唯一哈希
        cache_str = f"{request.prompt}_{request.style.value}_{request.duration}_{request.tempo}_{request.mood}"
        return hashlib.md5(cache_str.encode()).hexdigest()
    
    def _get_cached_music(
        self,
        request: MusicGenerationRequest
    ) -> Optional[MusicGenerationResult]:
        """获取缓存的音乐"""
        cache_key = self._get_cache_key(request)
        cache_file = self.cache_dir / f"{cache_key}.mp3"
        
        if cache_file.exists():
            with open(cache_file, 'rb') as f:
                audio_data = f.read()
            
            self._update_music_index(request, cache_file)
            
            return MusicGenerationResult(
                success=True,
                audio_file_path=str(cache_file),
                audio_data=audio_data,
                duration=request.duration,
                file_size=len(audio_data),
                cost=0.0,  # 缓存不计费
                cached=True
            )
        
        return None
    
    def _save_to_cache(
        self,
        request: MusicGenerationRequest,
        result: MusicGenerationResult
    ):
        """保存到缓存"""
        cache_key = self._get_cache_key(request)
        cache_file = self.cache_dir / f"{cache_key}.mp3"
        
        # 如果result已有文件路径，直接复制
        if result.audio_file_path and Path(result.audio_file_path).exists():
            import shutil
            shutil.copy(result.audio_file_path, cache_file)
        # 否则写入audio_data
        elif result.audio_data:
            with open(cache_file, 'wb') as f:
                f.write(result.audio_data)
        
        self._update_music_index(request, cache_file)
        logger.debug(f"💾 音乐已缓存: {cache_file.name}")
    
    def _update_music_index(
        self,
        request: MusicGenerationRequest,
        cache_file: Path,
    ) -> None:
        """更新本地音乐索引，便于后续检索和复用"""
        try:
            index_data = []
            if self.index_path.exists():
                with self.index_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        index_data = data
            cache_key = self._get_cache_key(request)
            record = {
                "id": cache_key,
                "prompt": request.prompt,
                "style": request.style.value,
                "duration": request.duration,
                "tempo": request.tempo,
                "mood": request.mood,
                "instruments": request.instruments,
                "file_path": str(cache_file),
                "source": "mureka",
            }
            index_data = [r for r in index_data if r.get("id") != cache_key]
            index_data.append(record)
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            with self.index_path.open("w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"⚠️ 更新音乐索引失败: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        cache_rate = (self.cache_hits / max(1, self.total_requests + self.cache_hits)) * 100
        
        return {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "cache_rate": f"{cache_rate:.1f}%",
            "total_cost": f"¥{self.total_cost:.2f}",
            "cached_files": len(list(self.cache_dir.glob("*.mp3")))
        }


class AIMusicGenerator:
    """
    AI音乐生成器 - 高级封装
    
    提供情绪→风格映射、智能参数推荐等功能
    """
    
    # 情绪→风格映射表
    MOOD_TO_STYLE_MAP = {
        "tense": MusicStyle.SUSPENSE,       # 紧张→悬疑
        "mysterious": MusicStyle.CHINESE_STYLE,  # 神秘→国风
        "sad": MusicStyle.CLASSICAL,        # 悲伤→古典
        "exciting": MusicStyle.ELECTRONIC,  # 兴奋→电子
        "calm": MusicStyle.AMBIENT,         # 平静→氛围
        "romantic": MusicStyle.ROMANTIC,    # 浪漫→浪漫
        "epic": MusicStyle.EPIC,           # 史诗→史诗
        "joyful": MusicStyle.POP,          # 欢快→流行
    }
    
    # 场景→配乐建议
    SCENE_MUSIC_TEMPLATES = {
        "开场": {
            "prompt": "引人入胜的开场音乐，营造故事氛围",
            "duration": 15,
            "tempo": "medium"
        },
        "高潮": {
            "prompt": "紧张激烈的高潮音乐，推动情节发展",
            "duration": 30,
            "tempo": "fast"
        },
        "转折": {
            "prompt": "神秘悬疑的转折音乐，暗示剧情变化",
            "duration": 20,
            "tempo": "slow"
        },
        "结尾": {
            "prompt": "舒缓余韵的结尾音乐，留下想象空间",
            "duration": 20,
            "tempo": "slow"
        }
    }
    
    def __init__(self, mureka_client: Optional[MurekaO1Client] = None):
        """
        Args:
            mureka_client: Mureka客户端（可选，默认自动创建）
        """
        self.client = mureka_client or MurekaO1Client()
    
    async def generate_for_scene(
        self,
        scene_description: str,
        mood: str = "calm",
        duration: int = 30
    ) -> MusicGenerationResult:
        """
        为场景生成配乐
        
        Args:
            scene_description: 场景描述，如"雨夜的城市街道"
            mood: 情绪
            duration: 时长
        
        Returns:
            音乐生成结果
        """
        # 智能选择风格
        style = self.MOOD_TO_STYLE_MAP.get(mood, MusicStyle.AMBIENT)
        
        # 构造Prompt
        prompt = f"{mood}情绪的背景音乐，适合{scene_description}场景，{style.value}风格"
        
        request = MusicGenerationRequest(
            prompt=prompt,
            style=style,
            duration=duration,
            mood=mood,
            tempo=self._infer_tempo(mood)
        )
        
        logger.info(f"🎼 为场景生成音乐: {scene_description[:30]}...")
        return await self.client.generate_music(request)
    
    async def generate_theme_music(
        self,
        character_name: str,
        personality: str,
        duration: int = 30
    ) -> MusicGenerationResult:
        """
        为角色生成主题音乐
        
        Args:
            character_name: 角色名
            personality: 性格描述，如"高冷神秘"
            duration: 时长
        
        Returns:
            音乐生成结果
        """
        # 根据性格推断情绪
        mood = self._personality_to_mood(personality)
        style = self.MOOD_TO_STYLE_MAP.get(mood, MusicStyle.AMBIENT)
        
        prompt = f"{character_name}的主题音乐，体现{personality}的性格，{style.value}风格"
        
        request = MusicGenerationRequest(
            prompt=prompt,
            style=style,
            duration=duration,
            mood=mood
        )
        
        logger.info(f"🎵 为角色生成主题音乐: {character_name}")
        return await self.client.generate_music(request)
    
    def _infer_tempo(self, mood: str) -> str:
        """根据情绪推断节奏"""
        if mood in ["exciting", "tense"]:
            return "fast"
        elif mood in ["sad", "calm", "romantic"]:
            return "slow"
        else:
            return "medium"
    
    def _personality_to_mood(self, personality: str) -> str:
        """性格→情绪映射"""
        keyword_map = {
            "神秘": "mysterious",
            "高冷": "calm",
            "温柔": "romantic",
            "活泼": "joyful",
            "英勇": "epic",
            "悲伤": "sad",
        }
        
        for keyword, mood in keyword_map.items():
            if keyword in personality:
                return mood
        
        return "calm"  # 默认
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.client.get_statistics()


# 快捷工厂函数
def create_music_generator(
    api_key: Optional[str] = None,
    enable_cache: bool = True
) -> AIMusicGenerator:
    """
    创建AI音乐生成器
    
    Args:
        api_key: Mureka API密钥
        enable_cache: 是否启用缓存
    
    Returns:
        AI音乐生成器实例
    """
    client = MurekaO1Client(api_key=api_key, enable_cache=enable_cache)
    return AIMusicGenerator(mureka_client=client)
