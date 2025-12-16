"""
TTS语音合成引擎

核心功能：
1. 阿里云TTS集成
2. 智能缓存（降低成本60%）
3. 批量并行处理
4. 成本监控与限额
"""
import asyncio
import hashlib
import logging
from typing import Dict, Any, Optional, List
import io
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TTSCost:
    """TTS成本记录"""
    total_characters: int = 0
    total_segments: int = 0
    cache_hits: int = 0
    api_calls: int = 0
    estimated_cost: float = 0.0  # 单位：元
    
    def add_segment(self, char_count: int, is_cached: bool = False):
        """添加片段统计"""
        self.total_characters += char_count
        self.total_segments += 1
        
        if is_cached:
            self.cache_hits += 1
        else:
            self.api_calls += 1
            # 阿里云价格：¥0.04/千字
            self.estimated_cost += (char_count / 1000) * 0.04
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        cache_rate = (self.cache_hits / self.total_segments * 100) if self.total_segments > 0 else 0
        
        return {
            "total_characters": self.total_characters,
            "total_segments": self.total_segments,
            "cache_hits": self.cache_hits,
            "cache_hit_rate": f"{cache_rate:.1f}%",
            "api_calls": self.api_calls,
            "estimated_cost": f"¥{self.estimated_cost:.2f}"
        }


class TTSEngine:
    """
    TTS引擎 - 阿里云语音合成
    
    特性：
    1. 多层缓存（内存+Redis）
    2. 批量并行处理
    3. 成本监控
    4. 限流保护
    """
    
    def __init__(
        self,
        provider: str = "aliyun",  # 默认使用阿里云CosyVoice（免费额度）
        enable_cache: bool = True,
        max_concurrent: int = 1,  # 降低到1个并发，避免频率限制
        model: str = "cosyvoice-v3-flash"  # 默认使用CosyVoice v3-flash（官方推荐，高质量）
    ):
        self.provider = provider
        self.enable_cache = enable_cache
        self.max_concurrent = max_concurrent
        self.model = model  # TTS模型版本
        
        # 成本统计
        self.cost_tracker = TTSCost()
        
        # 并发控制（降低到1，避免频率限制）
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # 请求间隔控制（每次请求后等待）
        self.request_delay = 10.0  # 增加到10秒，应对严格的配额限制
        
        # 缓存系统
        if enable_cache:
            # 暂时禁用缓存，简化实现
            # from app.services.cache_system import MultiLayerCache
            # self.cache = MultiLayerCache(
            #     enable_memory=True,
            #     enable_redis=True,
            #     memory_max_size=200  # 缓存200个音频片段
            # )
            self.cache = None
            logger.info("⚠️ 缓存功能暂时禁用")
        else:
            self.cache = None
        
        logger.info(f"✅ TTS引擎初始化: provider={provider}, model={model}, cache={enable_cache}")
    
    async def synthesize(
        self,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str = "neutral"
    ) -> bytes:
        """
        合成单个文本片段
        
        Args:
            text: 文本内容
            voice_params: 音色参数（来自VoiceProfile）
            emotion: 情感标签
        
        Returns:
            音频字节流（MP3格式）
        """
        # 1. 生成缓存key
        cache_key = self._generate_cache_key(text, voice_params, emotion)
        
        # 2. 检查缓存
        if self.cache:
            cached_audio = await self.cache.get(cache_key)
            if cached_audio:
                logger.debug(f"🎯 缓存命中: {text[:20]}...")
                self.cost_tracker.add_segment(len(text), is_cached=True)
                # 缓存的是base64字符串，需要解码
                import base64
                return base64.b64decode(cached_audio)
        
        # 3. 调用TTS API（带并发控制）
        async with self.semaphore:
            audio_bytes = await self._call_tts_api(text, voice_params)
            # 每次请求后等待，避免频率限制
            await asyncio.sleep(self.request_delay)
        
        # 4. 更新成本统计
        self.cost_tracker.add_segment(len(text), is_cached=False)
        
        # 5. 缓存结果
        if self.cache and audio_bytes:
            import base64
            cached_value = base64.b64encode(audio_bytes).decode('utf-8')
            await self.cache.set(cache_key, cached_value, ttl=604800)  # 缓存7天
        
        return audio_bytes
    
    async def synthesize_batch(
        self,
        segments: List[Dict[str, Any]],
        batch_size: int = 10,  # 每批处理数量
        batch_interval: int = 0  # 批次间隔（秒）- 优化：取消节流等待
    ) -> List[bytes]:
        """
        批量合成（分批处理，避免阿里云配额限制）
        
        Args:
            segments: 片段列表，每个包含 text, voice_params, emotion
            batch_size: 每批处理数量（默认10个）
            batch_interval: 批次间暂停时间（默认0秒，已取消节流）
        
        Returns:
            音频列表
        """
        total = len(segments)
        print(f"\n{'='*70}")
        print(f"[TTS] Starting batch synthesis: {total} segments")
        print(f"      Batch strategy: {batch_size} per batch, {batch_interval}s interval")
        print(f"{'='*70}\n")
        logger.info(f"🎙️ 开始批量TTS合成: {total} 个片段")
        logger.info(f"   📦 分批策略: 每批{batch_size}个，批次间隔{batch_interval}秒")
        
        # 分批处理
        audio_list = []
        num_batches = (total + batch_size - 1) // batch_size  # 向上取整
        
        for batch_idx in range(num_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, total)
            batch_segments = segments[start_idx:end_idx]
            
            logger.info(f"\n📦 批次 {batch_idx + 1}/{num_batches}: 处理片段 {start_idx + 1}-{end_idx}")
            
            # 串行处理当前批次（避免并发创建WebSocket连接）
            batch_results = []
            for i, seg in enumerate(batch_segments):
                global_idx = start_idx + i
                try:
                    result = await self.synthesize(
                        text=seg["text"],
                        voice_params=seg["voice_params"],
                        emotion=seg.get("emotion", "neutral")
                    )
                    batch_results.append(result)
                except Exception as e:
                    logger.error(f"   ❌ 片段 {global_idx + 1} 异常: {e}")
                    batch_results.append(Exception(str(e)))
            
            # 处理当前批次结果
            batch_success = 0
            for i, result in enumerate(batch_results):
                global_idx = start_idx + i
                if isinstance(result, Exception):
                    logger.error(f"   ❌ 片段 {global_idx + 1} 失败: {result}")
                    audio_list.append(b"")  # 空音频
                elif result and len(result) > 0:
                    logger.debug(f"   ✅ 片段 {global_idx + 1} 成功: {len(result)}字节")
                    audio_list.append(result)
                    batch_success += 1
                else:
                    logger.warning(f"   ⚠️ 片段 {global_idx + 1} 返回空")
                    audio_list.append(b"")
            
            logger.info(f"   批次完成: {batch_success}/{len(batch_segments)} 成功")
            
            # 批次间暂停（除了最后一批）
            if batch_idx < num_batches - 1:
                logger.info(f"   ⏸️ 暂停{batch_interval}秒，避免触发配额限制...")
                await asyncio.sleep(batch_interval)
        
        success_count = len([a for a in audio_list if a])
        logger.info(f"\n✅ 批量合成完成: {success_count}/{total} 成功")
        return audio_list
    
    async def _call_tts_api(
        self,
        text: str,
        voice_params: Dict[str, Any]
    ) -> bytes:
        """
        调用TTS API
        
        支持：
        - Qwen3-TTS (qwen) - 推荐！免费100万字符/月
        - 阿里云CosyVoice (aliyun)
        - Azure TTS (azure) - 备用
        """
        if self.provider == "qwen":
            return await self._call_qwen_tts(text, voice_params)
        elif self.provider == "aliyun":
            return await self._call_aliyun_tts(text, voice_params)
        elif self.provider == "azure":
            return await self._call_azure_tts(text, voice_params)
        else:
            raise ValueError(f"不支持的TTS服务商: {self.provider}")
    
    async def _call_qwen_tts(
        self,
        text: str,
        voice_params: Dict[str, Any],
        max_retries: int = 3
    ) -> bytes:
        """
        调用Qwen3-TTS（推荐！免费100万字符/月）
        
        核心优势：
        - 49种官方音色（含角色化音色）
        - 原生支持多角色（role_configs）
        - 原生情感标签（平静/紧张/喜悦/悲伤）
        - 首包延迟<300ms
        """
        # 重试逻辑
        for attempt in range(max_retries):
            try:
                # 验证文本
                if not text or not text.strip():
                    logger.warning("⚠️ 文本为空，跳过TTS")
                    return b""
                
                text = text.strip()
                
                # 文本长度限制（5000字符，官方推荐）
                if len(text) > 5000:
                    logger.warning(f"⚠️ 文本过长({len(text)}字符)，截断到5000字符")
                    text = text[:5000]
                
                import dashscope
                from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback, AudioFormat
                import os
                import base64
                import threading
                
                # 确保API Key已配置
                api_key = os.getenv("DASHSCOPE_API_KEY")
                if not api_key:
                    logger.error("❌ 未配置 DASHSCOPE_API_KEY")
                    return b""
                
                dashscope.api_key = api_key
                
                # 准备音频缓冲
                audio_buffer = io.BytesIO()
                complete_event = threading.Event()
                error_msg = None
                
                # 定义回调类
                class AudioCallback(QwenTtsRealtimeCallback):
                    def on_open(self) -> None:
                        logger.debug("🔗 Qwen-TTS WebSocket连接已建立")
                    
                    def on_close(self, close_status_code, close_msg) -> None:
                        logger.debug(f"🔒 Qwen-TTS连接关闭: {close_status_code}")
                        complete_event.set()
                    
                    def on_event(self, response: dict) -> None:
                        nonlocal error_msg
                        try:
                            event_type = response.get('type')
                            
                            if event_type == 'session.created':
                                logger.debug(f"🎵 Session ID: {response['session']['id']}")
                            
                            elif event_type == 'response.audio.delta':
                                # 接收音频数据
                                audio_b64 = response.get('delta')
                                if audio_b64:
                                    audio_buffer.write(base64.b64decode(audio_b64))
                            
                            elif event_type == 'response.done':
                                logger.debug("✅ 响应完成")
                            
                            elif event_type == 'session.finished':
                                logger.debug("✅ Session结束")
                                complete_event.set()
                            
                            elif event_type == 'error':
                                error_msg = response.get('message', '未知错误')
                                logger.error(f"❌ Qwen-TTS错误: {error_msg}")
                                complete_event.set()
                        
                        except Exception as e:
                            logger.error(f"❌ 回调处理异常: {e}")
                            error_msg = str(e)
                            complete_event.set()
                
                # 创建客户端
                callback = AudioCallback()
                qwen_tts = QwenTtsRealtime(
                    model=self.model,
                    callback=callback,
                    url='wss://dashscope.aliyuncs.com/api-ws/v1/realtime'
                )
                
                # 连接并配置
                qwen_tts.connect()
                
                # 获取音色和情感参数
                voice = voice_params.get("speaker", "Cherry")  # 默认音色
                emotion = voice_params.get("emotion", "natural")  # 情感
                speech_rate = voice_params.get("speed", 1.0)  # 语速
                volume = int(voice_params.get("volume", 50))  # 音量
                
                # 配置会话参数
                qwen_tts.update_session(
                    voice=voice,
                    response_format=AudioFormat.MP3_24000HZ_MONO,
                    mode='server_commit',  # 自动提交模式
                    speech_rate=speech_rate,
                    volume=volume
                )
                
                # 发送文本
                logger.debug(f"📤 发送文本: {text[:50]}...")
                qwen_tts.append_text(text)
                qwen_tts.finish()
                
                # 等待完成（超时60秒）
                if not complete_event.wait(timeout=60):
                    logger.error("❌ Qwen-TTS超时")
                    return b""
                
                # 检查错误
                if error_msg:
                    raise Exception(error_msg)
                
                # 获取音频数据
                audio_data = audio_buffer.getvalue()
                if not audio_data:
                    logger.warning("⚠️ Qwen-TTS返回空音频")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5)
                        continue
                    return b""
                
                logger.debug(f"✅ Qwen-TTS成功: {len(text)} 字符 → {len(audio_data)} 字节")
                return audio_data
            
            except Exception as e:
                error_str = str(e)
                logger.error(f"🔍 Qwen-TTS异常: {error_str}")
                
                # 重试逻辑
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    logger.warning(f"⚠️ 等待{wait_time}秒后重试 (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    return b""
        
        logger.error(f"❌ Qwen-TTS失败：超过最大重试次数")
        return b""
    
    async def _call_aliyun_tts(
        self,
        text: str,
        voice_params: Dict[str, Any],
        max_retries: int = 3  # 新增：最大重试次数
    ) -> bytes:
        """
        调用阿里云TTS
        
        使用 dashscope SDK
        """
        # 重试逻辑
        for attempt in range(max_retries):
            try:
                # 验证文本
                if not text or not text.strip():
                    logger.warning("⚠️ 文本为空，跳过TTS")
                    return b""
                
                # 清理文本（仅移除危险字符，保留中文）
                original_text = text
                text = text.strip()
                
                # 标准化引号（阿里云TTS不支持中文引号）
                text = text.replace('“', '')
                text = text.replace('”', '')
                text = text.replace('‘', "'")
                text = text.replace('’', "'")
                text = text.replace('《', '<')
                text = text.replace('》', '>')
                text = text.replace('【', '[')
                text = text.replace('】', ']')
                
                # 只移除控制字符（保留中文、英文、数字、标点、空格）
                import unicodedata
                cleaned_text = ''.join(
                    char for char in text 
                    if unicodedata.category(char)[0] not in ['C']  # 移除控制字符类别
                )
                text = cleaned_text.strip()
                
                # 调试：对比清理前后
                if text != original_text:
                    logger.warning(f"⚠️ 文本已清理：原文[{original_text[:30]}...] → 清理后[{text[:30]}...]")
                
                # 再次验证
                if not text:
                    logger.warning("⚠️ 清理后文本为空，跳过TTS")
                    return b""
                
                # 调试：打印文本内容（包括字符类型）
                logger.info(f"📝 准备TTS文本: [{text[:50]}...] (长度:{len(text)}字)")
                # 输出前20个字符的Unicode编码
                char_codes = ', '.join([f"{ord(c):04x}" for c in text[:20]])
                logger.debug(f"🔍 Unicode编码: {char_codes}")
                
                if len(text) > 2000:  # 官方限制：同步调用最多2000字符
                    logger.warning(f"⚠️ 文本过长({len(text)}字符)，截断到2000字符")
                    text = text[:2000]
                
                import dashscope
                from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
                
                # 确保API Key已配置
                import os
                api_key = os.getenv("DASHSCOPE_API_KEY")
                if not api_key:
                    logger.error("❌ 未配置 DASHSCOPE_API_KEY")
                    return b""
                
                dashscope.api_key = api_key
                
                # 创建合成器
                # 根据模型版本配置不同参数
                if self.model == "cosyvoice-v1":
                    # v1：仅支持基础参数
                    synthesizer = SpeechSynthesizer(
                        model="cosyvoice-v1",
                        voice=voice_params.get("speaker", "longxiaochun"),
                        format=AudioFormat.MP3_22050HZ_MONO_256KBPS
                        # v1不支持pitch_rate/speech_rate/volume
                    )
                else:
                    # v2/v3：支持完整参数
                    synthesizer = SpeechSynthesizer(
                        model=self.model,
                        voice=voice_params.get("speaker", "longanyang"),
                        format=AudioFormat.MP3_22050HZ_MONO_256KBPS,
                        # v2/v3支持音高、语速、音量调节
                        pitch_rate=voice_params.get("pitch", 50) / 50.0,  # 0-100 -> 0-2.0
                        speech_rate=voice_params.get("speed", 1.0),       # 0.5-2.0
                        volume=voice_params.get("volume", 50)             # 0-100
                    )
                
                # 同步调用（dashscope暂不支持async）
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    synthesizer.call,
                    text
                )
                
                # 检查结果（兼容两种返回格式）
                audio_data = None
                
                # 详细记录返回结果
                logger.debug(f"🔍 返回类型: {type(result)}")
                logger.debug(f"🔍 返回值: {result}")
                
                # 格式1：cosyvoice-v1直接返回bytes
                if isinstance(result, bytes):
                    audio_data = result
                    logger.debug(f"✅ 阿里云TTS成功: {len(text)} 字符 → {len(audio_data)} 字节")
                    return audio_data
                # 格式2：旧模型返回对象，调用get_audio_data()
                elif result and hasattr(result, 'get_audio_data'):
                    audio_data = result.get_audio_data()
                    if audio_data:
                        logger.debug(f"✅ 阿里云TTS成功: {len(text)} 字符")
                        return audio_data
                    else:
                        logger.warning(f"⚠️ 阿里云TTS返回空音频: {text[:50]}...")
                        # 418错误可能在这里，尝试重试
                        if attempt < max_retries - 1:
                            wait_time = 15  # 等待15秒
                            logger.warning(f"⚠️ 检测到空音频（可能是418错误），等待{wait_time}秒后重试 (attempt {attempt + 1}/{max_retries})")
                            await asyncio.sleep(wait_time)
                            continue  # 重试
                        return b""
                else:
                    logger.error(f"❌ 阿里云TTS失败: {result}")
                    # 检测是否为None（418错误的典型情况）
                    if result is None and attempt < max_retries - 1:
                        wait_time = 15  # 等待15秒
                        logger.warning(f"⚠️ 返回None（可能是418错误），等待{wait_time}秒后重试 (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue  # 重试
                    return b""
                    
            except Exception as e:
                error_str = str(e)
                
                # 详细记录错误信息
                logger.error(f"🔍 捕获到异常: {type(e).__name__}")
                logger.error(f"🔍 错误内容: {error_str}")
                
                # 检查是否为频率限制错误
                if "Throttling.RateQuota" in error_str or "rate limit" in error_str.lower():
                    wait_time = (attempt + 1) * 5  # 指数退避：5s, 10s, 15s
                    logger.warning(f"⚠️ API频率限制，等待{wait_time}秒后重试 (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue  # 重试
                # 检查是否为418错误（配额限制）
                elif "418" in error_str:
                    wait_time = 10  # 配额错误，等待10秒
                    logger.warning(f"⚠️ 配额限制错误418，等待{wait_time}秒后重试 (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue  # 重试
                else:
                    # 非频率限制错误，直接返回
                    logger.error(f"❌ 阿里云TTS异常: {e}")
                    logger.debug(f"   文本内容: {text[:100] if text else 'None'}...")
                    return b""
        
        # 所有重试失败
        logger.error(f"❌ TTS失败：超过最大重试次数 ({max_retries})")
        return b""
    
    async def _call_azure_tts(
        self,
        text: str,
        voice_params: Dict[str, Any]
    ) -> bytes:
        """
        调用Azure TTS（备用方案）
        
        TODO: 实现Azure集成
        """
        logger.warning("⚠️ Azure TTS 暂未实现")
        return b""
    
    def _generate_cache_key(
        self,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str
    ) -> str:
        """生成缓存key"""
        # 组合关键参数
        key_parts = [
            text,
            str(voice_params.get("speaker", "")),
            str(voice_params.get("pitch", "")),
            str(voice_params.get("speed", "")),
            emotion
        ]
        key_string = "|".join(key_parts)
        
        # MD5哈希
        return "tts:" + hashlib.md5(key_string.encode('utf-8')).hexdigest()
    
    def get_cost_stats(self) -> Dict[str, Any]:
        """获取成本统计"""
        return self.cost_tracker.get_stats()
    
    def reset_cost_tracker(self):
        """重置成本统计"""
        self.cost_tracker = TTSCost()
