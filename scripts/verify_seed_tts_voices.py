#!/usr/bin/env python3
"""
验证 Seed-TTS 2.0 Expressive 对所有音色的 API 调用。
不下载音频文件，仅验证 API 调用是否成功。
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
SEED_TTS_MODEL = "seed-tts-2.0-expressive"
DEFAULT_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_RESOURCE_ID = "seed-tts-2.0"


def _get_seed_tts_api_key() -> str:
    """获取 Seed-TTS API Key"""
    env_names = [
        "VOLCENGINE_TTS_API_KEY",
        "DOUBAO_TTS_API_KEY",
        "SEED_TTS_API_KEY",
        "VOLCENGINE_SPEECH_API_KEY",
        "DOUBAO_SPEECH_API_KEY",
    ]
    for env_name in env_names:
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    raise EnvironmentError(
        "未找到 Seed-TTS API Key，请设置以下环境变量之一: " + ", ".join(env_names)
    )


def load_voices_from_json() -> List[Dict[str, Any]]:
    """从 JSON 文件加载音色列表"""
    voices_file = PROJECT_ROOT / "shared" / "seed_tts_2_0_voices.json"
    
    if not voices_file.exists():
        raise FileNotFoundError(f"音色文件不存在: {voices_file}")
    
    with open(voices_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    voices = data.get("voices", [])
    logger.info(f"从 {voices_file.name} 加载了 {len(voices)} 个音色")
    return voices


def _build_test_payload(voice_id: str, text: str = "你好，这是一个测试。") -> Dict[str, Any]:
    """构建 Seed-TTS HTTP API 请求载荷"""
    return {
        "user": {"uid": "audiobook"},
        "req_params": {
            "model": SEED_TTS_MODEL,
            "text": text,
            "text_type": "plain",
            "with_timestamp": 0,
            "speaker": voice_id,
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
                "speech_rate": 0,
                "loudness_rate": 0,
            },
        },
    }


async def test_single_voice(
    voice_id: str,
    api_key: str,
    endpoint: str = DEFAULT_ENDPOINT,
    resource_id: str = DEFAULT_RESOURCE_ID,
) -> Dict[str, Any]:
    """测试单个音色的 API 调用"""
    import httpx

    payload = _build_test_payload(voice_id)
    
    result = {
        "voice_id": voice_id,
        "success": False,
        "status_code": None,
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                endpoint,
                headers={
                    "X-Api-App-Key": api_key,
                    "X-Api-Key": api_key,
                    "X-Api-Resource-Id": resource_id,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            
            result["status_code"] = response.status_code
            
            if response.status_code == 200:
                # 验证响应内容是否包含有效的音频数据
                content_type = response.headers.get("content-type", "").lower()
                content_length = len(response.content)
                
                # 检查是否为音频流或包含音频数据的 JSON
                is_valid = False
                if content_type.startswith("audio/"):
                    # 直接返回音频流
                    is_valid = content_length > 0
                else:
                    # JSON 响应，需要检查是否包含音频数据
                    try:
                        # Seed-TTS 可能返回 JSON Lines 格式（多行）
                        lines = response.text.strip().splitlines()
                        has_audio = False
                        
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                                if isinstance(data, dict):
                                    # 检查常见的音频数据字段
                                    audio_data = (
                                        data.get("audio") or 
                                        data.get("data") or 
                                        data.get("output") or 
                                        data.get("result")
                                    )
                                    if isinstance(audio_data, str) and audio_data:
                                        has_audio = True
                                        break
                                    elif isinstance(audio_data, dict):
                                        # 嵌套结构，检查是否有 url 或 base64 数据
                                        nested_audio = (
                                            audio_data.get("audio") or
                                            audio_data.get("data") or
                                            audio_data.get("url")
                                        )
                                        if nested_audio:
                                            has_audio = True
                                            break
                            except json.JSONDecodeError:
                                continue
                        
                        is_valid = has_audio
                    except Exception:
                        # 如果不是 JSON，但有内容，也认为有效
                        is_valid = content_length > 0
                
                if is_valid:
                    result["success"] = True
                    logger.info(f"✓ {voice_id} - 成功 (status={response.status_code}, size={content_length} bytes)")
                else:
                    result["error"] = f"HTTP 200 but invalid audio data (content-type={content_type}, size={content_length})"
                    logger.error(f"✗ {voice_id} - 失败: {result['error']}")
            else:
                result["error"] = response.text[:200]
                logger.error(f"✗ {voice_id} - 失败 (status={response.status_code}): {result['error']}")
                
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"✗ {voice_id} - 异常: {e}")

    return result


async def verify_all_voices():
    """验证所有音色"""
    logger.info("=" * 80)
    logger.info("开始验证 Seed-TTS 2.0 Expressive 音色 API 调用")
    logger.info("=" * 80)

    # 加载音色列表
    try:
        voices = load_voices_from_json()
        logger.info(f"音色总数: {len(voices)}")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"加载音色列表失败: {e}")
        return

    # 获取 API Key
    try:
        api_key = _get_seed_tts_api_key()
        logger.info("API Key 已配置")
    except EnvironmentError as e:
        logger.error(str(e))
        return

    # 逐个测试音色
    results: List[Dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    
    for idx, voice in enumerate(voices, 1):
        voice_id = voice.get("id", "")
        label = voice.get("label", "N/A")
        
        if not voice_id:
            logger.warning(f"跳过无效音色 (index={idx})")
            continue
            
        logger.info(f"[{idx}/{len(voices)}] 测试音色: {voice_id} ({label})")
        
        result = await test_single_voice(voice_id, api_key)
        results.append(result)
        
        if result["success"]:
            success_count += 1
        else:
            failure_count += 1
        
        # 避免过快请求，添加小延迟
        await asyncio.sleep(0.5)

    # 输出统计结果
    logger.info("=" * 80)
    logger.info("验证完成！")
    logger.info("=" * 80)
    logger.info(f"总音色数: {len(voices)}")
    logger.info(f"成功: {success_count}")
    logger.info(f"失败: {failure_count}")
    logger.info(f"成功率: {success_count / len(voices) * 100:.2f}%")
    logger.info("=" * 80)

    # 输出失败的音色列表
    if failure_count > 0:
        logger.warning("\n失败的音色列表:")
        for result in results:
            if not result["success"]:
                logger.warning(
                    f"  - {result['voice_id']}: status={result['status_code']}, error={result['error']}"
                )

    # 保存结果到文件
    output_file = PROJECT_ROOT / "backend" / "tests" / "seed_tts_voice_verification_results.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": __import__("datetime").datetime.now().isoformat(),
                "model": SEED_TTS_MODEL,
                "total_voices": len(voices),
                "success_count": success_count,
                "failure_count": failure_count,
                "results": results,
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"\n详细结果已保存到: {output_file}")
    except Exception as e:
        logger.error(f"保存结果失败: {e}")


if __name__ == "__main__":
    asyncio.run(verify_all_voices())
