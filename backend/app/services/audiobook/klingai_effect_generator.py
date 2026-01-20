"""
可灵AI音效生成适配器

使用可灵AI的文生音效API生成环境音和音效
API文档: https://app.klingai.com/cn/dev/document-api/apiReference/model/textToAudio
"""

import logging
import asyncio
import hashlib
import time
from jose import jwt
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

import httpx
import requests
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class KlingAIEffectResult:
    """可灵AI音效生成结果"""
    success: bool
    audio_url_mp3: Optional[str] = None
    audio_url_wav: Optional[str] = None
    duration_mp3: Optional[float] = None
    duration_wav: Optional[float] = None
    task_id: Optional[str] = None
    error: Optional[str] = None
    local_file_path: Optional[str] = None


class KlingAIEffectGenerator:
    """可灵AI音效生成器
    
    使用可灵AI的文生音效API生成环境音和音效
    """
    
    def __init__(self, access_key: Optional[str] = None, secret_key: Optional[str] = None):
        """初始化可灵AI音效生成器
        
        Args:
            access_key: 可灵AI Access Key，如果不提供则从环境变量读取
            secret_key: 可灵AI Secret Key，如果不提供则从环境变量读取
        """
        self.access_key = access_key or getattr(settings, "KLINGAI_ACCESS_KEY", "") or ""
        self.secret_key = secret_key or getattr(settings, "KLINGAI_SECRET_KEY", "") or ""
        self.base_url = "https://api.klingai.com/v1/audio/text-to-audio"
        self.timeout = 120  # 超时时间（秒）
        self._cached_token = None
        self._token_expire_time = 0
        
        if not self.access_key or not self.secret_key:
            logger.warning("⚠️ 未配置可灵AI Access Key或Secret Key(KLINGAI_ACCESS_KEY/KLINGAI_SECRET_KEY)")
    
    def _generate_jwt_token(self) -> str:
        """生成JWT Token
        
        Returns:
            JWT Token字符串
        """
        current_time = int(time.time())
        
        headers = {
            "alg": "HS256",
            "typ": "JWT"
        }
        
        payload = {
            "iss": self.access_key,
            "exp": current_time + 1800,  # 有效时间30分钟
            "nbf": current_time - 5  # 5秒前生效
        }
        
        token = jwt.encode(payload, self.secret_key, headers=headers)
        return token
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        current_time = time.time()
        
        if self._cached_token and current_time < self._token_expire_time:
            token = self._cached_token
        else:
            token = self._generate_jwt_token()
            self._cached_token = token
            self._token_expire_time = current_time + 1700  # 提前100秒过期
        
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
    
    def _generate_task_id(self, prompt: str) -> str:
        """生成任务ID"""
        raw = f"{prompt}_{time.time()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    
    def create_task(
        self,
        prompt: str,
        duration: float = 5.0,
        external_task_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """创建音效生成任务
        
        Args:
            prompt: 文本提示词（不超过200字符）
            duration: 生成音频的时长（3.0-10.0秒）
            external_task_id: 自定义任务ID（可选）
        
        Returns:
            任务信息，失败返回None
        """
        if not self.access_key or not self.secret_key:
            logger.error("❌ 未配置可灵AI API密钥")
            return None
        
        # 限制prompt长度
        prompt = prompt[:200]
        
        # 限制duration范围
        duration = max(3.0, min(10.0, duration))
        
        # 生成任务ID
        task_id = external_task_id or self._generate_task_id(prompt)
        
        payload = {
            "prompt": prompt,
            "duration": round(duration, 1)
        }
        
        if external_task_id:
            payload["external_task_id"] = external_task_id
        
        try:
            logger.info(f"🎧 [可灵AI] 创建音效生成任务: {prompt} (时长: {duration}s)")
            
            response = requests.post(
                self.base_url,
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("code") == 0:
                task_info = data.get("data", {})
                logger.info(f"✅ 任务创建成功: {task_info.get('task_id')}")
                return task_info
            else:
                logger.error(f"❌ 任务创建失败: {data.get('message')}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 创建任务请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ 创建任务异常: {e}")
            return None
    
    def query_task(
        self,
        task_id: str,
        external_task_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """查询任务状态
        
        Args:
            task_id: 任务ID
            external_task_id: 自定义任务ID（可选）
        
        Returns:
            任务信息，失败返回None
        """
        if not self.access_key or not self.secret_key:
            logger.error("❌ 未配置可灵AI API密钥")
            return None
        
        try:
            # 构建查询URL
            if task_id:
                url = f"{self.base_url}/{task_id}"
            elif external_task_id:
                url = f"{self.base_url}?external_task_id={external_task_id}"
            else:
                logger.error("❌ 必须提供task_id或external_task_id")
                return None
            
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("code") == 0:
                return data.get("data")
            else:
                logger.error(f"❌ 查询任务失败: {data.get('message')}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 查询任务请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ 查询任务异常: {e}")
            return None
    
    def generate_effect(
        self,
        prompt: str,
        duration: float = 5.0,
        max_wait: int = 60,
        poll_interval: float = 2.0
    ) -> KlingAIEffectResult:
        """生成音效（同步方式，等待完成）
        
        Args:
            prompt: 文本提示词
            duration: 生成音频的时长（3.0-10.0秒）
            max_wait: 最大等待时间（秒）
            poll_interval: 轮询间隔（秒）
        
        Returns:
            音效生成结果
        """
        if not self.access_key or not self.secret_key:
            return KlingAIEffectResult(
                success=False,
                error="未配置可灵AI API密钥"
            )
        
        # 1. 创建任务
        task_info = self.create_task(prompt, duration)
        if not task_info:
            return KlingAIEffectResult(
                success=False,
                error="创建任务失败"
            )
        
        task_id = task_info.get("task_id")
        if not task_id:
            return KlingAIEffectResult(
                success=False,
                error="任务ID为空"
            )
        
        # 2. 轮询任务状态
        start_time = time.time()
        while time.time() - start_time < max_wait:
            result = self.query_task(task_id)
            if not result:
                time.sleep(poll_interval)
                continue
            
            task_status = result.get("task_status")
            
            if task_status == "succeed":
                task_result = result.get("task_result", {})
                audios = task_result.get("audios", [])
                
                if audios:
                    audio_data = audios[0]
                    return KlingAIEffectResult(
                        success=True,
                        audio_url_mp3=audio_data.get("url_mp3"),
                        audio_url_wav=audio_data.get("url_wav"),
                        duration_mp3=float(audio_data.get("duration_mp3", 0)),
                        duration_wav=float(audio_data.get("duration_wav", 0)),
                        task_id=task_id
                    )
                else:
                    return KlingAIEffectResult(
                        success=False,
                        error="任务结果中没有音频数据"
                    )
            
            elif task_status == "failed":
                error_msg = result.get("task_status_msg", "未知错误")
                logger.error(f"❌ 任务失败: {error_msg}")
                return KlingAIEffectResult(
                    success=False,
                    error=error_msg
                )
            
            elif task_status in ["submitted", "processing"]:
                logger.info(f"⏳ 任务状态: {task_status}")
                time.sleep(poll_interval)
            else:
                logger.warning(f"⚠️ 未知任务状态: {task_status}")
                time.sleep(poll_interval)
        
        # 超时
        logger.error(f"❌ 任务超时（等待{max_wait}秒）")
        return KlingAIEffectResult(
            success=False,
            error=f"任务超时（等待{max_wait}秒）"
        )
    
    async def generate_effect_async(
        self,
        prompt: str,
        duration: float = 5.0,
        max_wait: int = 60,
        poll_interval: float = 2.0
    ) -> KlingAIEffectResult:
        """生成音效（异步方式）
        
        Args:
            prompt: 文本提示词
            duration: 生成音频的时长（3.0-10.0秒）
            max_wait: 最大等待时间（秒）
            poll_interval: 轮询间隔（秒）
        
        Returns:
            音效生成结果
        """
        if not self.access_key or not self.secret_key:
            return KlingAIEffectResult(
                success=False,
                error="未配置可灵AI API密钥"
            )
        
        # 限制prompt长度
        prompt = prompt[:200]
        
        # 限制duration范围
        duration = max(3.0, min(10.0, duration))
        
        # 生成任务ID
        task_id = self._generate_task_id(prompt)
        
        payload = {
            "prompt": prompt,
            "duration": round(duration, 1),
            "external_task_id": task_id
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 1. 创建任务
                logger.info(f"🎧 [可灵AI] 创建音效生成任务: {prompt} (时长: {duration}s)")
                
                response = await client.post(
                    self.base_url,
                    json=payload,
                    headers=self._get_headers()
                )
                response.raise_for_status()
                
                data = response.json()
                
                if data.get("code") != 0:
                    logger.error(f"❌ 任务创建失败: {data.get('message')}")
                    return KlingAIEffectResult(
                        success=False,
                        error=data.get("message")
                    )
                
                task_info = data.get("data", {})
                actual_task_id = task_info.get("task_id")
                
                # 2. 轮询任务状态
                start_time = time.time()
                while time.time() - start_time < max_wait:
                    response = await client.get(
                        f"{self.base_url}/{actual_task_id}",
                        headers=self._get_headers()
                    )
                    response.raise_for_status()
                    
                    data = response.json()
                    if data.get("code") != 0:
                        logger.error(f"❌ 查询任务失败: {data.get('message')}")
                        time.sleep(poll_interval)
                        continue
                    
                    result = data.get("data", {})
                    task_status = result.get("task_status")
                    
                    if task_status == "succeed":
                        task_result = result.get("task_result", {})
                        audios = task_result.get("audios", [])
                        
                        if audios:
                            audio_data = audios[0]
                            logger.info(f"✅ 音效生成成功: {prompt}")
                            return KlingAIEffectResult(
                                success=True,
                                audio_url_mp3=audio_data.get("url_mp3"),
                                audio_url_wav=audio_data.get("url_wav"),
                                duration_mp3=float(audio_data.get("duration_mp3", 0)),
                                duration_wav=float(audio_data.get("duration_wav", 0)),
                                task_id=actual_task_id
                            )
                    
                    elif task_status == "failed":
                        error_msg = result.get("task_status_msg", "未知错误")
                        logger.error(f"❌ 任务失败: {error_msg}")
                        return KlingAIEffectResult(
                            success=False,
                            error=error_msg
                        )
                    
                    await asyncio.sleep(poll_interval)
                
                # 超时
                logger.error(f"❌ 任务超时（等待{max_wait}秒）")
                return KlingAIEffectResult(
                    success=False,
                    error=f"任务超时（等待{max_wait}秒）"
                )
                
        except httpx.RequestError as e:
            logger.error(f"❌ 请求失败: {e}")
            return KlingAIEffectResult(
                success=False,
                error=str(e)
            )
        except Exception as e:
            logger.error(f"❌ 异常: {e}")
            return KlingAIEffectResult(
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
            url: 音频URL
            save_path: 保存路径
            timeout: 超时时间（秒）
        
        Returns:
            是否成功
        """
        try:
            logger.info(f"📥 下载音频: {url}")
            
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
            
            logger.info(f"✅ 音频下载成功: {save_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 下载音频失败: {e}")
            return False
    
    def generate_and_download(
        self,
        prompt: str,
        save_path: Path,
        duration: float = 5.0,
        format: str = "mp3",
        max_wait: int = 60
    ) -> KlingAIEffectResult:
        """生成音效并下载到本地
        
        Args:
            prompt: 文本提示词
            save_path: 保存路径
            duration: 生成音频的时长（3.0-10.0秒）
            format: 音频格式（mp3/wav）
            max_wait: 最大等待时间（秒）
        
        Returns:
            音效生成结果
        """
        # 1. 生成音效
        result = self.generate_effect(prompt, duration, max_wait)
        
        if not result.success:
            return result
        
        # 2. 下载音频
        url = result.audio_url_mp3 if format.lower() == "mp3" else result.audio_url_wav
        
        if not url:
            return KlingAIEffectResult(
                success=False,
                error="音频URL为空"
            )
        
        # 3. 下载到本地
        if self.download_audio(url, save_path):
            result.local_file_path = str(save_path)
            return result
        else:
            return KlingAIEffectResult(
                success=False,
                error="下载音频失败"
            )


def create_klingai_generator(
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None
) -> KlingAIEffectGenerator:
    """创建可灵AI音效生成器工厂函数
    
    Args:
        access_key: 可灵AI Access Key
        secret_key: 可灵AI Secret Key
    
    Returns:
        可灵AI音效生成器实例
    """
    return KlingAIEffectGenerator(
        access_key=access_key,
        secret_key=secret_key
    )
