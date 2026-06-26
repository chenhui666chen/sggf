#!/usr/bin/env python3
"""
Seed-TTS 2.0 WebSocket 批量验证脚本(独立版本)
不依赖项目内部模块,直接使用 websocket-client 库
"""
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import websocket

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent

# Constants
SEED_TTS_MODEL = "seed-tts-2.0-expressive"
DEFAULT_TEST_TEXT = "你好，这是一个测试。"
WS_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"


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
        raise ValueError("未找到 Seed-TTS API Key,请设置环境变量 VOLCENGINE_TTS_API_KEY")
    
    return api_key


def test_single_voice_websocket(
    voice_id: str,
    api_key: str,
    text: str = DEFAULT_TEST_TEXT,
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    使用 WebSocket 测试单个音色(同步阻塞)
    
    Returns:
        Dict with keys: voice_id, success, error, audio_size, duration_ms
    """
    result = {
        "voice_id": voice_id,
        "success": False,
        "error": None,
        "audio_size": 0,
        "duration_ms": 0,
    }
    
    session_id = str(uuid.uuid4())
    audio_chunks: List[bytes] = []
    error_state: Dict[str, Any] = {"error": None, "error_code": None}
    
    # Build req_params
    req_params = {
        "model": SEED_TTS_MODEL,
        "speaker": voice_id,
        "audio_params": {
            "format": "mp3",
            "sample_rate": 24000,
            "speech_rate": 0,
            "loudness_rate": 0,
        },
    }
    
    def on_open(ws):
        # Send StartConnection
        start_connection = {"EventType": "StartConnection"}
        ws.send(json.dumps(start_connection))
    
    def on_message(ws, message):
        # Handle binary audio data
        if isinstance(message, (bytes, bytearray)):
            audio_chunks.append(bytes(message))
            return
        
        # Parse JSON message
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        
        event_type = payload.get("event_type") or payload.get("EventType")
        
        # Handle different events
        if event_type == "ConnectionStarted":
            # Send StartSession
            start_session = {
                "EventType": "StartSession",
                "session_id": session_id,
                "req_params": req_params,
            }
            ws.send(json.dumps(start_session))
            return
        
        if event_type == "SessionStarted":
            # Send TaskRequest
            task_request = {
                "EventType": "TaskRequest",
                "session_id": session_id,
                "text": text,
            }
            ws.send(json.dumps(task_request))
            return
        
        if event_type == "SessionFinished":
            # Send FinishSession
            finish_session = {
                "EventType": "FinishSession",
                "session_id": session_id,
            }
            ws.send(json.dumps(finish_session))
            return
        
        if event_type == "ConnectionFinished":
            ws.close()
            return
        
        if event_type in ("SessionFailed", "ConnectionFailed"):
            error_msg = payload.get("payload", {}).get("message") or payload.get("message", "Unknown error")
            error_state["error"] = error_msg
            error_state["error_code"] = payload.get("code")
            ws.close()
            return
    
    def on_error(ws, error):
        error_state["error"] = str(error)
    
    def on_close(ws, close_status_code, close_msg):
        pass
    
    try:
        start_time = time.time()
        
        # Create WebSocket connection
        ws = websocket.WebSocketApp(
            WS_URL,
            header={
                "X-Api-Key": api_key,
                "X-Api-Resource-Id": "seed-tts-2.0",
            },
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        
        # Run WebSocket with timeout
        ws.run_forever(ping_timeout=10, ping_interval=30)
        
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        # Check for errors
        if error_state["error"]:
            error_code = error_state.get("error_code")
            if error_code:
                result["error"] = f"{error_code}: {error_state['error']}"
            else:
                result["error"] = error_state["error"]
            return result
        
        # Validate audio data
        if not audio_chunks:
            result["error"] = "No audio data received"
            return result
        
        # Combine audio chunks
        audio_result = b"".join(audio_chunks)
        
        result["success"] = True
        result["audio_size"] = len(audio_result)
        result["duration_ms"] = duration_ms
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def verify_all_voices_websocket():
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
        
        result = test_single_voice_websocket(voice_id, api_key)
        results.append(result)
        
        if result["success"]:
            success_count += 1
            logger.info(f"✓ {voice_id} - 成功 ({result['audio_size']} bytes, {result['duration_ms']}ms)")
        else:
            failure_count += 1
            logger.error(f"✗ {voice_id} - 失败: {result['error']}")
        
        # Small delay to avoid rate limiting
        time.sleep(0.5)
    
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
    results_file = PROJECT_ROOT / "backend" / "tests" / "seed_tts_websocket_verification_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "model": SEED_TTS_MODEL,
        "protocol": "websocket",
        "endpoint": WS_URL,
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
        success = verify_all_voices_websocket()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.warning("\n验证被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
