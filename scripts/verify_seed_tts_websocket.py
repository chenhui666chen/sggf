#!/usr/bin/env python3
"""
Seed-TTS 2.0 WebSocket 批量验证脚本
验证所有 99 个音色的 WebSocket API 调用是否正常
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Constants
SEED_TTS_MODEL = "seed-tts-2.0-expressive"
DEFAULT_TEST_TEXT = "你好，这是一个测试。"


def load_voices_from_json() -> List[Dict[str, Any]]:
    """从 JSON 文件加载音色列表"""
    voices_file = PROJECT_ROOT / "shared" / "seed_tts_2_0_voices.json"
    if not voices_file.exists():
        raise FileNotFoundError(f"音色配置文件不存在: {voices_file}")
    
    with open(voices_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return data.get("voices", [])


def get_seed_tts_api_key() -> str:
    """获取 Seed-TTS API Key"""
    api_key = os.getenv("VOLCENGINE_TTS_API_KEY") or \
              os.getenv("DOUBAO_TTS_API_KEY") or \
              os.getenv("SEED_TTS_API_KEY")
    
    if not api_key:
        raise ValueError("未找到 Seed-TTS API Key，请设置环境变量 VOLCENGINE_TTS_API_KEY")
    
    return api_key


async def test_single_voice_websocket(
    voice_id: str,
    api_key: str,
    text: str = DEFAULT_TEST_TEXT,
) -> Dict[str, Any]:
    """
    使用 WebSocket 测试单个音色
    
    Returns:
        Dict with keys: voice_id, success, error, audio_size, duration_ms
    """
    from app.services.audiobook.tts_engine_pkg._aliyun_mixin import AliyunMixin
    
    result = {
        "voice_id": voice_id,
        "success": False,
        "error": None,
        "audio_size": 0,
        "duration_ms": 0,
    }
    
    try:
        # Create mixin instance
        mixin = AliyunMixin()
        
        # Test parameters
        voice_params = {
            "format": "mp3",
            "sample_rate": 24000,
            "speed": 1.0,
            "volume": 50,
            "pitch": 50,
        }
        
        start_time = asyncio.get_event_loop().time()
        
        # Call WebSocket method
        audio_data = await mixin._call_seed_tts_websocket(
            model=SEED_TTS_MODEL,
            api_key=api_key,
            text=text,
            voice=voice_id,
            voice_params=voice_params,
        )
        
        end_time = asyncio.get_event_loop().time()
        duration_ms = int((end_time - start_time) * 1000)
        
        result["success"] = True
        result["audio_size"] = len(audio_data)
        result["duration_ms"] = duration_ms
        
        logger.info(f"✓ {voice_id} - 成功 ({len(audio_data)} bytes, {duration_ms}ms)")
        
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"✗ {voice_id} - 失败: {e}")
    
    return result


async def verify_all_voices_websocket():
    """验证所有音色"""
    logger.info("=" * 80)
    logger.info("Seed-TTS 2.0 Expressive WebSocket 批量验证")
    logger.info("=" * 80)
    
    # Load configuration
    voices = load_voices_from_json()
    api_key = get_seed_tts_api_key()
    
    total_voices = len(voices)
    logger.info(f"总音色数: {total_voices}")
    logger.info(f"测试文本: '{DEFAULT_TEST_TEXT}'")
    logger.info("-" * 80)
    
    # Results storage
    results = []
    success_count = 0
    failure_count = 0
    
    # Test each voice sequentially (WebSocket is synchronous)
    for idx, voice_info in enumerate(voices, 1):
        voice_id = voice_info.get("id") or voice_info.get("speaker")
        label = voice_info.get("label", "")
        
        logger.info(f"[{idx}/{total_voices}] 测试音色: {voice_id} ({label})")
        
        result = await test_single_voice_websocket(voice_id, api_key)
        results.append(result)
        
        if result["success"]:
            success_count += 1
        else:
            failure_count += 1
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)
    
    # Summary
    logger.info("=" * 80)
    logger.info("验证完成!")
    logger.info(f"总音色数: {total_voices}")
    logger.info(f"成功: {success_count}")
    logger.info(f"失败: {failure_count}")
    logger.info(f"成功率: {success_count/total_voices*100:.2f}%")
    logger.info("=" * 80)
    
    # Show failures
    if failure_count > 0:
        logger.warning("\n失败的音色列表:")
        for result in results:
            if not result["success"]:
                logger.warning(f"  - {result['voice_id']}: {result['error']}")
    
    # Save results to file
    results_file = BACKEND_DIR / "tests" / "seed_tts_websocket_verification_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "model": SEED_TTS_MODEL,
        "protocol": "websocket",
        "endpoint": "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
        "test_text": DEFAULT_TEST_TEXT,
        "total_voices": total_voices,
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
    }
    
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n结果已保存到: {results_file}")
    
    return success_count == total_voices


if __name__ == "__main__":
    # Load environment variables from .env.local
    env_file = PROJECT_ROOT / ".env.local"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()
    
    # Run verification
    try:
        success = asyncio.run(verify_all_voices_websocket())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.warning("\n验证被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
