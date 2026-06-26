#!/usr/bin/env python3
"""Debug single voice WebSocket connection - Try different methods"""
import json
import os
import uuid
from pathlib import Path

import websocket

# Load environment variables from .env.local
PROJECT_ROOT = Path(__file__).parent.parent
env_file = PROJECT_ROOT / ".env.local"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

# Configuration
ws_url_base = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
api_key = os.getenv("VOLCENGINE_TTS_API_KEY") or os.getenv("DOUBAO_TTS_API_KEY")
resource_id = os.getenv("VOLCENGINE_TTS_RESOURCE_ID", "seed-tts-2.0")
session_id = str(uuid.uuid4())

print(f"Base URL: {ws_url_base}")
print(f"API Key: {api_key[:20] if api_key else 'NOT SET'}...")
print(f"Resource ID: {resource_id}")
print(f"Session ID: {session_id}")
print("=" * 80)

# Test text
req_params = {
    "model": "seed-tts-2.0-expressive",
    "speaker": "zh_female_vv_uranus_bigtts",
    "audio_params": {
        "format": "mp3",
        "sample_rate": 24000,
        "speech_rate": 0,
        "loudness_rate": 0,
    },
}

text = "你好，这是一个测试。"

# Try multiple methods
def try_method(method_name, ws_url, headers):
    """Try a specific connection method"""
    print(f"\n{'='*80}")
    print(f"Testing: {method_name}")
    print(f"URL: {ws_url}")
    print(f"Headers: {headers}")
    print('=' * 80)
    
    audio_chunks = []
    events = []
    error_state = {"error": None, "code": None}
    
    def on_open(ws):
        print("\n[OPEN] WebSocket connected")
        start_conn = {"EventType": "StartConnection"}
        print(f"[SEND] {json.dumps(start_conn)}")
        ws.send(json.dumps(start_conn))
    
    def on_message(ws, message):
        if isinstance(message, (bytes, bytearray)):
            print(f"\n[BINARY] Received {len(message)} bytes")
            if len(message) < 200:
                print(f"  Hex: {message.hex()}")
                try:
                    # Try to decode as UTF-8 (skip first 16 bytes header)
                    text_data = message[16:].decode('utf-8', errors='replace')
                    print(f"  Text (after 16 bytes): {text_data}")
                except:
                    pass
            audio_chunks.append(bytes(message))
            return
        
        try:
            payload = json.loads(message)
            events.append(payload)
            event_type = payload.get("event_type") or payload.get("EventType")
            print(f"\n[RECV] Event: {event_type}")
            print(f"  Payload: {json.dumps(payload, ensure_ascii=False, indent=2)[:500]}")
            
            if event_type == "ConnectionStarted":
                print(f"\n[SUCCESS!] Connection established!")
                print(f"\n[SEND] StartSession")
                start_session = {
                    "EventType": "StartSession",
                    "session_id": session_id,
                    "req_params": req_params,
                }
                print(f"  {json.dumps(start_session, ensure_ascii=False)[:300]}")
                ws.send(json.dumps(start_session))
                return
            
            if event_type == "SessionStarted":
                print(f"\n[SEND] TaskRequest")
                task_request = {
                    "EventType": "TaskRequest",
                    "session_id": session_id,
                    "text": text,
                }
                print(f"  {json.dumps(task_request, ensure_ascii=False)}")
                ws.send(json.dumps(task_request))
                return
            
            if event_type == "SessionFinished":
                print(f"\n[SEND] FinishSession")
                finish_session = {
                    "EventType": "FinishSession",
                    "session_id": session_id,
                }
                ws.send(json.dumps(finish_session))
                return
            
            if event_type == "ConnectionFinished":
                print(f"\n[CLOSE] Connection finished")
                ws.close()
                return
            
            if event_type in ("SessionFailed", "ConnectionFailed"):
                error_msg = payload.get("payload", {}).get("message") or payload.get("message", "Unknown")
                error_state["error"] = error_msg
                error_state["code"] = payload.get("code")
                print(f"\n[ERROR] {error_state['code']}: {error_state['error']}")
                ws.close()
                return
                
        except Exception as e:
            print(f"\n[PARSE ERROR] {e}")
            print(f"  Raw message: {message[:200]}")
    
    def on_error(ws, error):
        print(f"\n[WS ERROR] {error}")
        error_state["error"] = str(error)
    
    def on_close(ws, close_status_code, close_msg):
        print(f"\n[CLOSE] Status: {close_status_code}, Message: {close_msg}")
    
    ws = websocket.WebSocketApp(
        ws_url,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    
    ws.run_forever(ping_timeout=10, ping_interval=30)
    
    print(f"\nResult: {len(events)} events, {len(audio_chunks)} audio chunks")
    print(f"Error state: {error_state}")
    
    return len(events) > 0 and any(e.get("EventType") == "ConnectionStarted" for e in events)

# Method 1: Standard with headers (current - fails)
try_method(
    "Method 1: Standard headers",
    ws_url_base,
    {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
    }
)

# Method 2: With version parameter in URL
try_method(
    "Method 2: URL with version=v1",
    f"{ws_url_base}?version=v1",
    {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
    }
)

# Method 3: With version=2.0
try_method(
    "Method 3: URL with version=2.0",
    f"{ws_url_base}?version=2.0",
    {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
    }
)

# Method 4: Add X-Api-Version header
try_method(
    "Method 4: With X-Api-Version header",
    ws_url_base,
    {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Version": "2.0",
    }
)

print("\n" + "=" * 80)
print("All methods tested. Check results above.")
