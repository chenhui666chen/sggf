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

# 全局并发控制：限制同时调用 Mureka API 的协程数量，避免触发服务端QPS限制
# 可通过环境变量 MUREKA_MAX_CONCURRENT 配置，默认值为 1（严格顺序：一个完成再下一个）
_MUREKA_MAX_CONCURRENT = int(os.getenv("MUREKA_MAX_CONCURRENT", "1"))
_MUREKA_MAX_CONCURRENT = max(1, _MUREKA_MAX_CONCURRENT)
_MUREKA_SEMAPHORE = asyncio.Semaphore(_MUREKA_MAX_CONCURRENT)


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
        # Mureka 官方 API 地址（根据官方文档：https://platform.mureka.cn/docs/cn/quickstart.html）
        self.api_base = os.getenv("MUREKA_API_URL") or getattr(settings, "MUREKA_API_URL", "https://api.mureka.cn")
        if not self.api_key:
            logger.warning("⚠️ MUREKA_API_KEY未设置，AI音乐生成将使用模拟模式")
        
        self.enable_cache = enable_cache
        # 🔧 修复：cache_dir 转换为绝对路径，避免在不同工作目录下创建重复目录
        # ai_music.py 位于 backend/app/services/audiobook/，parents[4] = 项目根目录
        cache_dir_path = Path(cache_dir)
        if not cache_dir_path.is_absolute():
            # 相对路径：相对于项目根目录
            project_root = Path(__file__).resolve().parents[4]
            cache_dir_path = project_root / cache_dir
        
        self.cache_dir = cache_dir_path
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir.parent / "music_index.json"
        
        # 成本统计
        self.total_requests = 0
        self.cache_hits = 0
        self.total_cost = 0.0
        
        # 🆕 水印裁剪配置
        # 从环境变量或配置文件读取裁剪时长，默认3秒
        self.watermark_trim_seconds = float(
            os.getenv("MUREKA_WATERMARK_TRIM") or 
            getattr(settings, "MUREKA_WATERMARK_TRIM", 3.0)
        )
        if self.watermark_trim_seconds > 0:
            logger.info(f"✂️ 启用Mureka水印自动裁剪: {self.watermark_trim_seconds}秒")
        
        logger.info(f"✅ MurekaO1客户端初始化完成 (cache={enable_cache})")
    
    async def generate_music(
        self,
        request: MusicGenerationRequest
    ) -> MusicGenerationResult:
        """生成音乐（带全局并发控制）
        
        Args:
            request: 音乐生成请求
        
        Returns:
            音乐生成结果
        """
        # 通过全局信号量限制同时在飞的 Mureka 请求数量
        async with _MUREKA_SEMAPHORE:
            return await self._generate_music_inner(request)

    async def _generate_music_inner(
        self,
        request: MusicGenerationRequest
    ) -> MusicGenerationResult:
        """实际执行音乐生成的内部实现（不再单独做并发控制）"""
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
            # Mureka 官方 API Endpoint（根据官方文档：https://platform.mureka.cn/docs/api/operations/post-v1-instrumental-generate.html）
            # 使用 /v1/instrumental/generate 生成纯音乐/环境音（无人声）
            base_url = self.api_base.rstrip("/")
            endpoint = f"{base_url}/v1/instrumental/generate"

            # 根据官方 API 格式构造请求：使用 prompt 描述风格
            # 将我们的结构化参数转换为 Mureka 的 prompt 格式
            prompt_parts = []
            if request.mood:
                prompt_parts.append(request.mood)
            if request.style:
                prompt_parts.append(request.style.value)
            if request.tempo:
                prompt_parts.append(request.tempo)
            if request.instruments:
                prompt_parts.extend(request.instruments)
            if request.prompt:
                prompt_parts.append(request.prompt)
            
            combined_prompt = ", ".join(prompt_parts) if prompt_parts else request.prompt

            payload = {
                "prompt": combined_prompt,  # 风格描述，如 "tense, suspense, slow, piano"
                "model": "auto",           # 自动选择模型
                "duration": request.duration,  # 时长（秒）
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

            # 根据官方文档，接口返回任务信息：{"id": "...", "status": "preparing", "model": "...", ...}
            # 需要轮询任务状态直到完成，然后获取音频 URL
            task_data = resp.json()
            task_id = task_data.get("id")
            if not task_id:
                raise RuntimeError(f"Mureka 返回数据中缺少 task id: {task_data}")
            
            logger.info(f"🎵 Mureka 任务已创建: {task_id}, 开始轮询状态...")
            
            # 轮询任务状态，直到完成或失败
            max_poll_time = int(os.getenv("TIME_OUT_SECONDS", "300"))  # 默认 5 分钟
            poll_interval = 5  # 每 5 秒查询一次
            start_time = asyncio.get_event_loop().time()
            
            audio_url = None
            duration = request.duration
            
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > max_poll_time:
                    raise RuntimeError(f"任务 {task_id} 超时（{max_poll_time}秒）")
                
                # 查询任务状态（使用 instrumental 专用查询接口）
                def _check_status():
                    status_url = f"{base_url}/v1/instrumental/query/{task_id}"
                    r = requests.get(status_url, headers=headers, timeout=30)
                    r.raise_for_status()
                    return r.json()
                
                status_data = await loop.run_in_executor(None, _check_status)
                status = status_data.get("status")
                
                logger.debug(f"🔍 任务 {task_id} 状态: {status} | 原始数据: {status_data}")
                
                # 兼容不同接口的状态字段：
                # - instrumental 文档常见: pending / running / succeeded / failed
                # - 早期文档: preparing / processing / completed
                if status in ["completed", "succeeded"]:
                    # 任务完成，获取音频 URL
                    # Mureka instrumental 接口返回格式：
                    # {
                    #   "choices": [
                    #     {"url": "xxx.mp3", "flac_url": "xxx.flac", "wav_url": "xxx.wav", "duration": 168190},
                    #     ...
                    #   ]
                    # }
                    # 我们优先使用第一个候选的 MP3 URL
                    choices = status_data.get("choices", [])
                    if choices and isinstance(choices, list) and len(choices) > 0:
                        first_choice = choices[0]
                        audio_url = first_choice.get("url")  # MP3 格式
                        # duration 单位是毫秒，转换为秒
                        duration_ms = first_choice.get("duration", request.duration * 1000)
                        duration = duration_ms / 1000.0
                    else:
                        # 兼容旧格式（如果顶层有 audio_url）
                        audio_url = (
                            status_data.get("audio_url")
                            or status_data.get("result", {}).get("audio_url")
                            or status_data.get("data", {}).get("audio_url")
                        )
                        duration = status_data.get("duration", duration)
                    
                    if not audio_url:
                        raise RuntimeError(f"任务完成但缺少 audio_url: {status_data}")
                    break
                elif status in ["failed", "error"]:
                    error_msg = status_data.get("error", {}).get("message", "未知错误")
                    raise RuntimeError(f"任务失败: {error_msg}")
                elif status in ["preparing", "processing", "queued", "pending", "running"]:
                    # 继续等待
                    await asyncio.sleep(poll_interval)
                else:
                    logger.warning(f"⚠️ 未知任务状态: {status}，继续等待...")
                    await asyncio.sleep(poll_interval)
            
            # 下载音频文件
            logger.info(f"⬇️ 下载音频: {audio_url}")
            
            def _download():
                r2 = requests.get(audio_url, timeout=300)
                r2.raise_for_status()
                return r2.content
            
            audio_data = await loop.run_in_executor(None, _download)
            cost = 0.0  # Mureka 计费需要根据实际情况调整

            # 🆕 自动去除Mureka水印（使用配置的裁剪时长）
            if self.watermark_trim_seconds > 0:
                audio_data = self._remove_mureka_watermark(
                    audio_data, 
                    trim_seconds=self.watermark_trim_seconds
                )

            # 将结果写入缓存目录的临时文件
            cache_key = self._get_cache_key(request)
            output_file = self.cache_dir / f"{cache_key}.mp3"
            with open(output_file, "wb") as f:
                f.write(audio_data)

            # 返回相对于 audio_library 的路径（而不是完整路径）
            # 这样 engine.py 可以正确拼接基础目录
            relative_path = output_file.relative_to(self.cache_dir.parent)
            
            return MusicGenerationResult(
                success=True,
                audio_file_path=str(relative_path),
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
        
        # 返回相对于 audio_library 的路径
        relative_path = output_file.relative_to(self.cache_dir.parent)
        
        return MusicGenerationResult(
            success=True,
            audio_file_path=str(relative_path),
            audio_data=audio_data,
            duration=request.duration,
            file_size=len(audio_data),
            cost=0.0,  # 模拟模式免费
            cached=False
        )
    
    def _get_cache_key(self, request: MusicGenerationRequest) -> str:
        """生成缓存键
        
        优化策略：只基于核心风格参数，而非完整prompt，让同类场景能复用音乐。
        例如：所有"悬疑场景"共用一个缓存，避免因场景细节不同而反复生成。
        """
        # 只取 prompt 前100个字符作为风格标识（去掉场景具体描述）
        # 这样"悬疑场景铺垫配乐...\n\n场景描述：XXX"会被截断为"悬疑场景铺垫配乐..."
        prompt_key = request.prompt[:100] if request.prompt else ""
        
        # 基于核心风格参数生成缓存键（而非完整prompt）
        cache_str = f"{prompt_key}_{request.style.value}_{request.duration}_{request.tempo}_{request.mood}"
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
            
            # 返回相对于 audio_library 的路径
            relative_path = cache_file.relative_to(self.cache_dir.parent)
            
            return MusicGenerationResult(
                success=True,
                audio_file_path=str(relative_path),
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
        
        # 如果result已有文件路径，复制或移动
        if result.audio_file_path and Path(result.audio_file_path).exists():
            import shutil
            source_path = Path(result.audio_file_path)
            # 如果源文件和目标文件不是同一个文件，才复制
            if source_path.resolve() != cache_file.resolve():
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
    
    def _remove_mureka_watermark(
        self,
        audio_data: bytes,
        trim_seconds: float = 3.0
    ) -> bytes:
        """
        🆕 自动去除Mureka水印（裁剪末尾）
        
        Args:
            audio_data: 原始音频数据
            trim_seconds: 裁剪末尾时长（秒），默认3秒
        
        Returns:
            去除水印后的音频数据
        """
        try:
            # 尝试使用pydub裁剪
            try:
                from pydub import AudioSegment
                import io
                
                audio = AudioSegment.from_file(io.BytesIO(audio_data))
                original_duration_ms = len(audio)
                
                # 裁剪末尾
                trim_ms = int(trim_seconds * 1000)
                if original_duration_ms > trim_ms:
                    trimmed_audio = audio[:-trim_ms]
                    
                    # 输出
                    output_buffer = io.BytesIO()
                    trimmed_audio.export(output_buffer, format="mp3", bitrate="128k")
                    
                    logger.info(
                        f"✂️ 已自动去除Mureka水印: "
                        f"{original_duration_ms/1000:.1f}s → {len(trimmed_audio)/1000:.1f}s "
                        f"(裁剪{trim_seconds}s)"
                    )
                    return output_buffer.getvalue()
                else:
                    logger.warning(f"⚠️ 音频太短({original_duration_ms/1000:.1f}s)，跳过水印裁剪")
                    return audio_data
                    
            except ImportError:
                logger.warning("⚠️ pydub不可用，无法裁剪水印")
                return audio_data
                
        except Exception as e:
            logger.warning(f"⚠️ 裁剪水印失败: {e}，返回原始音频")
            return audio_data
    
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
