#!/usr/bin/env python3
"""
Seed-TTS 2.0 Expressive WebSocket 批量验证脚本 (v2 - 使用正确的二进制帧协议)
基于官方Python示例实现
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

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

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
        
        try:
            # Start connection - send binary frame
            await send_binary_frame(websocket, build_start_connection_frame())
            
            # Wait for ConnectionStarted
            msg = await receive_message(websocket)
            if msg["type"] != "FullServerResponse" or msg["event"] != "ConnectionStarted":
                raise RuntimeError(f"Expected ConnectionStarted, got {msg}")
            
            logger.debug("Connection started successfully")
            
            # Start session
            start_session_request = copy.deepcopy(base_request)
            start_session_request["event"] = 100  # EventType.StartSession
            await send_binary_frame(
                websocket, 
                build_session_frame(start_session_request, session_id)
            )
            
            # Wait for SessionStarted
            msg = await receive_message(websocket)
            if msg["type"] != "FullServerResponse" or msg["event"] != "SessionStarted":
                raise RuntimeError(f"Expected SessionStarted, got {msg}")
            
            logger.debug("Session started successfully")
            
            # Send TaskRequest with full text
            task_request_data = copy.deepcopy(base_request)
            task_request_data["event"] = 200  # EventType.TaskRequest
            task_request_data["req_params"]["text"] = text
            
            await send_binary_frame(
                websocket,
                build_session_frame(task_request_data, session_id)
            )
            
            logger.debug("Task request sent")
            
            # Receive audio data and events
            while True:
                msg = await receive_message(websocket, timeout=10)
                
                if msg["type"] == "FullServerResponse":
                    if msg["event"] == "SessionFinished":
                        logger.debug("Session finished")
                        break
                    elif msg["event"] in ("SessionFailed", "ConnectionFailed"):
                        error_msg = msg.get("payload", {}).get("message", "Unknown error")
                        raise RuntimeError(f"TTS failed: {error_msg}")
                
                elif msg["type"] == "AudioOnlyServer":
                    audio_received = True
                    audio_data.extend(msg["payload"])
                    logger.debug(f"Received audio chunk: {len(msg['payload'])} bytes")
            
            # Finish session
            await send_binary_frame(
                websocket,
                build_finish_session_frame(session_id)
            )
            
            # Wait for SessionFinished
            msg = await receive_message(websocket)
            if msg["type"] != "FullServerResponse" or msg["event"] != "SessionFinished":
                logger.warning(f"Expected SessionFinished, got {msg}")
            
            end_time = asyncio.get_event_loop().time()
            duration_ms = int((end_time - start_time) * 1000)
            
            if not audio_received:
                result["error"] = "No audio data received"
                return result
            
            result["success"] = True
            result["audio_size"] = len(audio_data)
            result["duration_ms"] = duration_ms
            
        finally:
            # Finish connection
            await send_binary_frame(websocket, build_finish_connection_frame())
            
            try:
                msg = await receive_message(websocket, timeout=5)
                if msg["type"] == "FullServerResponse" and msg["event"] == "ConnectionFinished":
                    logger.debug("Connection finished")
            except:
                pass
            
            await websocket.close()
            logger.debug("WebSocket closed")
    
    except asyncio.TimeoutError:
        result["error"] = "Timeout waiting for response"
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error testing {voice_id}: {e}")
    
    return result


# Binary frame building functions (based on official protocol)

def build_start_connection_frame() -> bytes:
    """Build StartConnection binary frame"""
    import struct
    
    frame = bytearray()
    frame.append(0b0001_0001)  # version=1, header_size=1
    frame.append(0b0001_0100)  # has_event_type=1, serialization=0
    frame.append(0b0001_0000)  # flags=0, compression=0
    frame.append(0b0000_0000)  # reserved
    
    # Event Type: START_CONNECTION (1)
    frame.extend(struct.pack(">i", 1))
    
    # Empty payload
    payload = json.dumps({}).encode()
    payload_len = struct.pack(">I", len(payload))
    
    return bytes(frame + payload_len + payload)


def build_session_frame(request_data: dict, session_id: str) -> bytes:
    """Build session-related binary frame (StartSession/TaskRequest/FinishSession)"""
    import struct
    
    frame = bytearray()
    frame.append(0b0001_0001)  # version=1, header_size=1
    frame.append(0b0001_0001)  # has_event_type=1, serialization=1 (JSON)
    frame.append(0b0001_0000)  # flags
    frame.append(0b0000_0000)  # reserved
    
    # Event Type
    event_type = request_data.get("event", 0)
    frame.extend(struct.pack(">i", event_type))
    
    # Session ID
    session_id_bytes = session_id.encode('utf-8')
    frame.extend(struct.pack(">I", len(session_id_bytes)))
    frame.extend(session_id_bytes)
    
    # Payload (request data without 'event' field)
    payload_data = {k: v for k, v in request_data.items() if k != "event"}
    payload_json = json.dumps(payload_data, ensure_ascii=False).encode('utf-8')
    frame.extend(struct.pack(">I", len(payload_json)))
    frame.extend(payload_json)
    
    return bytes(frame)


def build_finish_session_frame(session_id: str) -> bytes:
    """Build FinishSession frame"""
    import struct
    
    frame = bytearray()
    frame.append(0b0001_0001)
    frame.append(0b0001_0001)
    frame.append(0b0001_0000)
    frame.append(0b0000_0000)
    
    # Event Type: FINISH_SESSION (102)
    frame.extend(struct.pack(">i", 102))
    
    # Session ID
    session_id_bytes = session_id.encode('utf-8')
    frame.extend(struct.pack(">I", len(session_id_bytes)))
    frame.extend(session_id_bytes)
    
    # Empty payload
    frame.extend(struct.pack(">I", 0))
    
    return bytes(frame)


def build_finish_connection_frame() -> bytes:
    """Build FinishConnection frame"""
    import struct
    
    frame = bytearray()
    frame.append(0b0001_0001)
    frame.append(0b0001_0100)
    frame.append(0b0001_0000)
    frame.append(0b0000_0000)
    
    # Event Type: FINISH_CONNECTION (2)
    frame.extend(struct.pack(">i", 2))
    
    # Empty payload
    frame.extend(struct.pack(">I", 0))
    
    return bytes(frame)


async def send_binary_frame(websocket, frame: bytes):
    """Send binary frame via WebSocket"""
    await websocket.send(frame)


async def receive_message(websocket, timeout: float = 10) -> Dict[str, Any]:
    """Receive and parse message from WebSocket"""
    import struct
    
    try:
        message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError("Timeout waiting for message")
    
    if isinstance(message, (bytes, bytearray)):
        # Parse binary frame
        if len(message) < 12:
            raise RuntimeError(f"Message too short: {len(message)} bytes")
        
        # Parse header
        header = message[0:4]
        event_type = struct.unpack(">i", message[4:8])[0]
        
        # Parse session_id
        offset = 8
        session_id_len = struct.unpack(">I", message[offset:offset+4])[0]
        offset += 4
        
        session_id = ""
        if session_id_len > 0:
            session_id = message[offset:offset+session_id_len].decode('utf-8')
            offset += session_id_len
        
        # Parse payload length
        payload_len = struct.unpack(">I", message[offset:offset+4])[0]
        offset += 4
        
        # Determine message type based on header byte 2 bit 0 (serialization_method)
        # If serialization_method == 1, payload is JSON (FullServerResponse)
        # If serialization_method == 0, payload is raw bytes (AudioOnlyServer)
        serialization_method = header[1] & 0x0F
        
        if serialization_method == 1 and payload_len > 0:
            # JSON payload (FullServerResponse)
            payload_json = message[offset:offset+payload_len].decode('utf-8')
            payload_data = json.loads(payload_json)
            
            # Map event type number to name
            event_names = {
                50: "ConnectionStarted",
                51: "ConnectionFailed",
                52: "ConnectionFinished",
                100: "StartSession",
                102: "FinishSession",
                150: "SessionStarted",
                152: "SessionFinished",
                153: "SessionFailed",
                200: "TaskRequest",
                350: "TTSSentenceStart",
                351: "TTSSentenceEnd",
                352: "TTSResponse",
            }
            event_name = event_names.get(event_type, f"Unknown({event_type})")
            
            return {
                "type": "FullServerResponse",
                "event": event_name,
                "session_id": session_id,
                "payload": payload_data,
            }
        else:
            # Audio data or empty response (AudioOnlyServer or control message)
            audio_data = message[offset:offset+payload_len] if payload_len > 0 else b""
            
            event_names = {
                50: "ConnectionStarted",
                51: "ConnectionFailed",
                52: "ConnectionFinished",
                100: "StartSession",
                102: "FinishSession",
                150: "SessionStarted",
                152: "SessionFinished",
                153: "SessionFailed",
                200: "TaskRequest",
                350: "TTSSentenceStart",
                351: "TTSSentenceEnd",
                352: "TTSResponse",
            }
            event_name = event_names.get(event_type, f"Unknown({event_type})")
            
            # If it's a known event type with empty/small payload, treat as FullServerResponse
            if event_type in event_names and payload_len <= 10:
                try:
                    payload_text = audio_data.decode('utf-8', errors='replace')
                    if payload_text.strip() in ('{}', ''):
                        return {
                            "type": "FullServerResponse",
                            "event": event_name,
                            "session_id": session_id,
                            "payload": {},
                        }
                except:
                    pass
            
            # Otherwise treat as audio
            return {
                "type": "AudioOnlyServer",
                "event": event_name,
                "session_id": session_id,
                "payload": audio_data,
                "payload_size": len(audio_data),
            }
    
    else:
        # Text message (shouldn't happen with this protocol)
        return {
            "type": "TextMessage",
            "data": message,
        }


async def verify_all_voices_websocket():
    """验证所有音色"""
    logger.info("=" * 80)
    logger.info("Seed-TTS 2.0 Expressive WebSocket 批量验证 (v2 - 二进制帧协议)")
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
    results_file = PROJECT_ROOT / "backend" / "tests" / "seed_tts_websocket_verification_results_v2.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "model": SEED_TTS_MODEL,
        "protocol": "websocket_binary_frame",
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
