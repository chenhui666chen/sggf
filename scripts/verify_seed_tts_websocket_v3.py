#!/usr/bin/env python3
"""
Seed-TTS 2.0 Expressive WebSocket 批量验证脚本 (v3 - 使用官方 protocols.py)
基于火山引擎官方协议实现
"""
import asyncio
import copy
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path (protocols.py is in scripts directory)
PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent

# Insert scripts directory to find protocols.py
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import websockets

# Import protocols module from scripts directory
try:
    from protocols import (
        EventType,
        MsgType,
        finish_connection,
        finish_session,
        receive_message,
        start_connection,
        start_session,
        task_request,
        wait_for_event,
    )
except ImportError as e:
    print(f"ERROR: Failed to import protocols: {e}")
    print(f"Scripts directory: {SCRIPTS_DIR}")
    print(f"sys.path: {sys.path[:5]}")
    raise

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
logger.info(f"Successfully imported protocols from {SCRIPTS_DIR}")

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


async def test_single_voice_websocket(
    voice_id: str,
    api_key: str,
    text: str = DEFAULT_TEST_TEXT,
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    使用 WebSocket 测试单个音色(异步)
    
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
    
    connect_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    audio_data = bytearray()
    audio_received = False
    
    # Build req_params
    base_request = {
        "req_params": {
            "model": SEED_TTS_MODEL,
            "speaker": voice_id,
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
                "speech_rate": 0,
                "loudness_rate": 0,
            },
        },
    }
    
    websocket = None
    try:
        start_time = asyncio.get_event_loop().time()
        
        # Connect to server
        headers = {
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": "seed-tts-2.0",
            "X-Api-Connect-Id": connect_id,
            "X-Control-Require-Usage-Tokens-Return": "*",
        }
        
        logger.debug(f"Connecting to {WS_URL}")
        websocket = await websockets.connect(
            WS_URL, 
            additional_headers=headers, 
            max_size=10 * 1024 * 1024
        )
        logger.debug(f"Connected, Logid: {websocket.response.headers.get('x-tt-logid', 'N/A')}")
        
        # Start connection
        await start_connection(websocket)
        await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionStarted)
        logger.debug("Connection started successfully")
        
        # Start session
        start_session_request = copy.deepcopy(base_request)
        start_session_request["event"] = EventType.StartSession
        await start_session(
            websocket, 
            json.dumps(start_session_request).encode(), 
            session_id
        )
        await wait_for_event(websocket, MsgType.FullServerResponse, EventType.SessionStarted)
        logger.debug("Session started successfully")
        
        # Send TaskRequest with full text
        task_request_data = copy.deepcopy(base_request)
        task_request_data["event"] = EventType.TaskRequest
        task_request_data["req_params"]["text"] = text
        
        await task_request(
            websocket,
            json.dumps(task_request_data).encode(),
            session_id
        )
        logger.debug("Task request sent")
        
        # Receive audio data and events
        session_finished = False
        while not session_finished:
            try:
                msg = await asyncio.wait_for(receive_message(websocket), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for message after receiving {len(audio_data)} bytes")
                break
            
            if msg.type == MsgType.FullServerResponse:
                if msg.event == EventType.SessionFinished:
                    logger.debug("Session finished")
                    session_finished = True
                    break
                elif msg.event == EventType.TTSSentenceEnd:
                    logger.debug(f"Sentence ended: {msg.payload.decode('utf-8', errors='replace')[:100]}")
                elif msg.event in (EventType.SessionFailed, EventType.ConnectionFailed):
                    error_msg = msg.payload.decode('utf-8', errors='replace') if msg.payload else "Unknown error"
                    raise RuntimeError(f"TTS failed: {error_msg}")
            
            elif msg.type == MsgType.AudioOnlyServer:
                audio_received = True
                audio_data.extend(msg.payload)
                logger.debug(f"Received audio chunk: {len(msg.payload)} bytes")
        
        # Finish session
        await finish_session(websocket, session_id)
        
        end_time = asyncio.get_event_loop().time()
        duration_ms = int((end_time - start_time) * 1000)
        
        if not audio_received:
            result["error"] = "No audio data received"
            return result
        
        result["success"] = True
        result["audio_size"] = len(audio_data)
        result["duration_ms"] = duration_ms
    
    except asyncio.TimeoutError:
        result["error"] = "Timeout waiting for response"
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error testing {voice_id}: {e}")
    finally:
        if websocket:
            try:
                # Finish connection
                await finish_connection(websocket)
                try:
                    await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionFinished)
                    logger.debug("Connection finished")
                except:
                    pass
                await websocket.close()
                logger.debug("WebSocket closed")
            except Exception as e:
                logger.warning(f"Error closing websocket: {e}")
    
    return result


async def verify_all_voices_websocket():
    """验证所有音色"""
    logger.info("=" * 80)
    logger.info("Seed-TTS 2.0 Expressive WebSocket 批量验证 (v3 - 官方 protocols.py)")
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
    
    # Test each voice sequentially
    for idx, voice_info in enumerate(voices, 1):
        voice_id = voice_info.get("id") or voice_info.get("speaker")
        label = voice_info.get("label", "")
        
        logger.info(f"[{idx}/{total_voices}] 测试音色: {voice_id} ({label})")
        
        result = await test_single_voice_websocket(voice_id, api_key)
        results.append(result)
        
        if result["success"]:
            success_count += 1
            logger.info(f"✓ {voice_id} - 成功 ({result['audio_size']} bytes, {result['duration_ms']}ms)")
        else:
            failure_count += 1
            logger.error(f"✗ {voice_id} - 失败: {result['error']}")
        
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
    results_file = PROJECT_ROOT / "backend" / "tests" / "seed_tts_websocket_verification_results_v3.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "model": SEED_TTS_MODEL,
        "protocol": "websocket_official_protocols",
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
