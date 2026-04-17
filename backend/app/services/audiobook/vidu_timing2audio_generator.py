"""
Vidu Timing2Audio 音效生成适配器

使用 Vidu 的可控文生音效 API 生成时序音效
API 文档：https://www.vidu.cn/
"""

import logging
import asyncio
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

import httpx
import requests
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ViduTiming2AudioResult:
    """Vidu Timing2Audio 音效生成结果"""
    success: bool
    audio_url: Optional[str] = None
    duration: Optional[float] = None
    task_id: Optional[str] = None
    error: Optional[str] = None
    local_file_path: Optional[str] = None


class ViduTiming2AudioGenerator:
    """Vidu Timing2Audio 音效生成器
    
    使用 Vidu 的可控文生音效 API 生成时序音效
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """初始化 Vidu Timing2Audio 生成器
        
        Args:
            api_key: Vidu API Key，如果不提供则从环境变量读取
        """
        self.api_key = api_key or getattr(settings, "VIDU_API_KEY", "") or ""
        self.base_url = "https://api.vidu.cn/ent/v2"
        self.timeout = 120  # 超时时间（秒）
        
        if not self.api_key:
            logger.warning("⚠️ 未配置 Vidu API Key(VIDU_API_KEY)")
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Token {self.api_key}"
        }
    
    def _generate_task_id(self, timing_prompts: List[Dict], duration: float) -> str:
        """生成任务 ID"""
        raw = f"{str(timing_prompts)}_{duration}_{time.time()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    
    def create_task(
        self,
        timing_prompts: List[Dict[str, Any]],
        duration: float = 10.0,
        seed: Optional[int] = None,
        callback_url: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """创建音效生成任务
        
        Args:
            timing_prompts: 可控音效参数，描述多个音效事件及各自时间区间
            duration: 生成音频的时长（2.0-10.0 秒）
            seed: 随机种子
            callback_url: 回调 URL
        
        Returns:
            任务信息，失败返回 None
        """
        if not self.api_key:
            logger.error("❌ 未配置 Vidu API Key")
            return None
        
        # 限制 duration 范围
        duration = max(2.0, min(10.0, duration))
        
        # 构建请求体
        payload = {
            "model": "audio1.0",
            "duration": round(duration, 1),
            "timing_prompts": timing_prompts
        }
        
        if seed is not None and seed != 0:
            payload["seed"] = seed
        
        if callback_url:
            payload["callback_url"] = callback_url
        
        try:
            logger.info(f"🎧 [Vidu] 创建时序音效生成任务：{len(timing_prompts)}个事件 (时长：{duration}s)")
            
            response = requests.post(
                f"{self.base_url}/timing2audio",
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            if "task_id" in data:
                task_info = data
                logger.info(f"✅ 任务创建成功：{task_info.get('task_id')}")
                return task_info
            else:
                logger.error(f"❌ 任务创建失败：{data.get('message', 'Unknown error')}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 创建任务请求失败：{e}")
            return None
        except Exception as e:
            logger.error(f"❌ 创建任务异常：{e}")
            return None
    
    def query_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询任务状态
        
        Args:
            task_id: 任务 ID
        
        Returns:
            任务信息，失败返回 None
        """
        if not self.api_key:
            logger.error("❌ 未配置 Vidu API Key")
            return None
        
        try:
            response = requests.get(
                f"{self.base_url}/tasks/{task_id}",
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            
            if "task_id" in data:
                return data
            else:
                logger.error(f"❌ 查询任务失败：{data.get('message', 'Unknown error')}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 查询任务请求失败：{e}")
            return None
        except Exception as e:
            logger.error(f"❌ 查询任务异常：{e}")
            return None
    
    def generate_audio(
        self,
        timing_prompts: List[Dict[str, Any]],
        duration: float = 10.0,
        seed: Optional[int] = None,
        max_wait: int = 90,
        poll_interval: float = 3.0
    ) -> ViduTiming2AudioResult:
        """生成音效（同步方式，等待完成）
        
        Args:
            timing_prompts: 可控音效参数
            duration: 生成音频的时长（2.0-10.0 秒）
            seed: 随机种子
            max_wait: 最大等待时间（秒）
            poll_interval: 轮询间隔（秒）
        
        Returns:
            音效生成结果
        """
        if not self.api_key:
            return ViduTiming2AudioResult(
                success=False,
                error="未配置 Vidu API Key"
            )
        
        # 1. 创建任务
        task_info = self.create_task(timing_prompts, duration, seed)
        if not task_info:
            return ViduTiming2AudioResult(
                success=False,
                error="创建任务失败"
            )
        
        task_id = task_info.get("task_id")
        if not task_id:
            return ViduTiming2AudioResult(
                success=False,
                error="任务 ID 为空"
            )
        
        # 2. 轮询任务状态
        start_time = time.time()
        while time.time() - start_time < max_wait:
            result = self.query_task(task_id)
            if not result:
                time.sleep(poll_interval)
                continue
            
            state = result.get("state")
            
            if state == "success":
                # 任务成功，获取音频 URL
                audio_url = result.get("result", {}).get("audio_url")
                if audio_url:
                    logger.info(f"✅ 音效生成成功：{task_id}")
                    return ViduTiming2AudioResult(
                        success=True,
                        audio_url=audio_url,
                        duration=duration,
                        task_id=task_id
                    )
                else:
                    return ViduTiming2AudioResult(
                        success=False,
                        error="任务结果中没有音频 URL"
                    )
            
            elif state == "failed":
                error_msg = result.get("message", "未知错误")
                logger.error(f"❌ 任务失败：{error_msg}")
                return ViduTiming2AudioResult(
                    success=False,
                    error=error_msg
                )
            
            elif state in ["created", "queueing", "processing"]:
                logger.info(f"⏳ 任务状态：{state}")
                time.sleep(poll_interval)
            else:
                logger.warning(f"⚠️ 未知任务状态：{state}")
                time.sleep(poll_interval)
        
        # 超时
        logger.error(f"❌ 任务超时（等待{max_wait}秒）")
        return ViduTiming2AudioResult(
            success=False,
            error=f"任务超时（等待{max_wait}秒）"
        )
    
    async def generate_audio_async(
        self,
        timing_prompts: List[Dict[str, Any]],
        duration: float = 10.0,
        seed: Optional[int] = None,
        max_wait: int = 90,
        poll_interval: float = 3.0
    ) -> ViduTiming2AudioResult:
        """生成音效（异步方式）
        
        Args:
            timing_prompts: 可控音效参数
            duration: 生成音频的时长（2.0-10.0 秒）
            seed: 随机种子
            max_wait: 最大等待时间（秒）
            poll_interval: 轮询间隔（秒）
        
        Returns:
            音效生成结果
        """
        if not self.api_key:
            return ViduTiming2AudioResult(
                success=False,
                error="未配置 Vidu API Key"
            )
        
        # 限制 duration 范围
        duration = max(2.0, min(10.0, duration))
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 1. 创建任务
                payload = {
                    "model": "audio1.0",
                    "duration": round(duration, 1),
                    "timing_prompts": timing_prompts
                }
                
                if seed is not None and seed != 0:
                    payload["seed"] = seed
                
                logger.info(f"🎧 [Vidu] 创建时序音效生成任务：{len(timing_prompts)}个事件 (时长：{duration}s)")
                
                response = await client.post(
                    f"{self.base_url}/timing2audio",
                    json=payload,
                    headers=self._get_headers()
                )
                response.raise_for_status()
                
                data = response.json()
                
                if "task_id" not in data:
                    logger.error(f"❌ 任务创建失败：{data.get('message', 'Unknown error')}")
                    return ViduTiming2AudioResult(
                        success=False,
                        error=data.get("message", "Unknown error")
                    )
                
                task_id = data.get("task_id")
                
                # 2. 轮询任务状态
                start_time = time.time()
                while time.time() - start_time < max_wait:
                    response = await client.get(
                        f"{self.base_url}/tasks/{task_id}",
                        headers=self._get_headers()
                    )
                    response.raise_for_status()
                    
                    data = response.json()
                    state = data.get("state")
                    
                    if state == "success":
                        audio_url = data.get("result", {}).get("audio_url")
                        if audio_url:
                            logger.info(f"✅ 音效生成成功：{task_id}")
                            return ViduTiming2AudioResult(
                                success=True,
                                audio_url=audio_url,
                                duration=duration,
                                task_id=task_id
                            )
                        else:
                            return ViduTiming2AudioResult(
                                success=False,
                                error="任务结果中没有音频 URL"
                            )
                    
                    elif state == "failed":
                        error_msg = data.get("message", "未知错误")
                        logger.error(f"❌ 任务失败：{error_msg}")
                        return ViduTiming2AudioResult(
                            success=False,
                            error=error_msg
                        )
                    
                    await asyncio.sleep(poll_interval)
                
                # 超时
                logger.error(f"❌ 任务超时（等待{max_wait}秒）")
                return ViduTiming2AudioResult(
                    success=False,
                    error=f"任务超时（等待{max_wait}秒）"
                )
                
        except httpx.RequestError as e:
            logger.error(f"❌ 请求失败：{e}")
            return ViduTiming2AudioResult(
                success=False,
                error=str(e)
            )
        except Exception as e:
            logger.error(f"❌ 异常：{e}")
            return ViduTiming2AudioResult(
                success=False,
                error=str(e)
            )
    
    def download_audio(
        self,
        url: str,
        save_path: Path,
        timeout: int = 60
    ) -> bool:
        """下载音频文件
        
        Args:
            url: 音频 URL
            save_path: 保存路径
            timeout: 超时时间（秒）
        
        Returns:
            是否成功
        """
        try:
            logger.info(f"📥 下载音频：{url}")
            
            response = requests.get(
                url,
                timeout=timeout,
                stream=True
            )
            response.raise_for_status()
            
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"✅ 音频下载成功：{save_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 下载音频失败：{e}")
            return False
    
    def generate_and_download(
        self,
        timing_prompts: List[Dict[str, Any]],
        save_path: Path,
        duration: float = 10.0,
        format: str = "mp3",
        max_wait: int = 90
    ) -> ViduTiming2AudioResult:
        """生成音效并下载到本地
        
        Args:
            timing_prompts: 可控音效参数
            save_path: 保存路径
            duration: 生成音频的时长（2.0-10.0 秒）
            format: 音频格式（mp3/wav）
            max_wait: 最大等待时间（秒）
        
        Returns:
            音效生成结果
        """
        # 1. 生成音效
        result = self.generate_audio(timing_prompts, duration, max_wait=max_wait)
        
        if not result.success:
            return result
        
        # 2. 下载音频
        if not result.audio_url:
            return ViduTiming2AudioResult(
                success=False,
                error="音频 URL 为空"
            )
        
        # 3. 下载到本地
        if self.download_audio(result.audio_url, save_path):
            result.local_file_path = str(save_path)
            return result
        else:
            return ViduTiming2AudioResult(
                success=False,
                error="下载音频失败"
            )


def create_vidu_timing2audio_generator(
    api_key: Optional[str] = None
) -> ViduTiming2AudioGenerator:
    """创建 Vidu Timing2Audio 生成器工厂函数
    
    Args:
        api_key: Vidu API Key
    
    Returns:
        Vidu Timing2Audio 生成器实例
    """
    return ViduTiming2AudioGenerator(
        api_key=api_key
    )
